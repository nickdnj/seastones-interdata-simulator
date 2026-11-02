/*
 * sxlat CoreAudio backend (macOS): AUHAL output unit on the default output
 * device. Asks the device for the requested buffer size (per-client on
 * macOS; reverts when the process exits). Does NOT change the device's
 * sample rate: on a shared Mac that would disturb other apps, so the harness
 * uses the device's current nominal rate and reports it.
 *
 * Output latency reported = device latency + safety offset + stream latency
 * + one buffer (the HAL's IO cycle), all from the HAL's own properties.
 * Xruns: kAudioDeviceProcessorOverload notifications, plus callback gaps
 * over 1.5 periods counted separately as late_callbacks.
 */
#include "sxlat.h"

#include <AudioToolbox/AudioToolbox.h>
#include <CoreAudio/CoreAudio.h>
#include <mach/mach_time.h>
#include <stdio.h>
#include <string.h>

static AudioUnit g_unit;
static AudioDeviceID g_dev;
static sxlat_state *g_st;
static float g_scratch[8192 * 8];

static UInt32 get_u32(AudioObjectID obj, AudioObjectPropertySelector sel, AudioObjectPropertyScope scope) {
    AudioObjectPropertyAddress a = {sel, scope, kAudioObjectPropertyElementMain};
    UInt32 v = 0, sz = sizeof v;
    if (AudioObjectGetPropertyData(obj, &a, 0, NULL, &sz, &v) != noErr) return 0;
    return v;
}

static OSStatus overload_cb(AudioObjectID obj, UInt32 n, const AudioObjectPropertyAddress *addrs, void *ctx) {
    (void)obj;
    sxlat_state *st = ctx;
    for (UInt32 i = 0; i < n; i++)
        if (addrs[i].mSelector == kAudioDeviceProcessorOverload) atomic_fetch_add(&st->xruns, 1);
    return noErr;
}

static uint64_t host_to_ns(UInt64 ht) {
    static mach_timebase_info_data_t tb;
    if (tb.denom == 0) mach_timebase_info(&tb);
    return ht * tb.numer / tb.denom;
}

static OSStatus render_cb(void *ref, AudioUnitRenderActionFlags *flags, const AudioTimeStamp *ts, UInt32 bus,
                          UInt32 frames, AudioBufferList *io) {
    (void)ref;
    (void)flags;
    (void)bus;
    sxlat_state *st = g_st;
    uint64_t now = (ts && (ts->mFlags & kAudioTimeStampHostTimeValid)) ? host_to_ns(ts->mHostTime) : sxlat_now_ns();
    if (io->mNumberBuffers == 1) {
        sxlat_render(st, (float *)io->mBuffers[0].mData, frames, now);
    } else {
        /* non-interleaved: render interleaved into scratch, then split */
        if (frames * st->channels > sizeof g_scratch / sizeof g_scratch[0]) return -1;
        sxlat_render(st, g_scratch, frames, now);
        for (UInt32 b = 0; b < io->mNumberBuffers && b < st->channels; b++) {
            float *dst = io->mBuffers[b].mData;
            for (UInt32 i = 0; i < frames; i++) dst[i] = g_scratch[i * st->channels + b];
        }
    }
    return noErr;
}

int sxlat_backend_open(sxlat_state *st, const char *device, sxlat_backend_info *info) {
    snprintf(info->name, sizeof info->name, "coreaudio");
    snprintf(info->sched, sizeof info->sched, "coreaudio-managed real-time IO thread");
    g_st = st;
    if (device) fprintf(stderr, "sxlat: --device ignored on macOS; using the default output device\n");

    AudioObjectPropertyAddress a = {kAudioHardwarePropertyDefaultOutputDevice, kAudioObjectPropertyScopeGlobal,
                                    kAudioObjectPropertyElementMain};
    UInt32 sz = sizeof g_dev;
    if (AudioObjectGetPropertyData(kAudioObjectSystemObject, &a, 0, NULL, &sz, &g_dev) != noErr ||
        g_dev == kAudioObjectUnknown) {
        snprintf(info->device, sizeof info->device, "none");
        return -1;
    }
    CFStringRef cfname = NULL;
    AudioObjectPropertyAddress na = {kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
    sz = sizeof cfname;
    if (AudioObjectGetPropertyData(g_dev, &na, 0, NULL, &sz, &cfname) == noErr && cfname) {
        CFStringGetCString(cfname, info->device, sizeof info->device, kCFStringEncodingUTF8);
        CFRelease(cfname);
    }

    Float64 rate = 0;
    AudioObjectPropertyAddress ra = {kAudioDevicePropertyNominalSampleRate, kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
    sz = sizeof rate;
    AudioObjectGetPropertyData(g_dev, &ra, 0, NULL, &sz, &rate);
    if (rate > 0) st->rate = (uint32_t)rate;
    info->actual_rate = st->rate;

    /* request the buffer size (IO cycle) */
    UInt32 frames = st->period;
    AudioObjectPropertyAddress ba = {kAudioDevicePropertyBufferFrameSize, kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
    AudioObjectSetPropertyData(g_dev, &ba, 0, NULL, sizeof frames, &frames);

    AudioComponentDescription d = {kAudioUnitType_Output, kAudioUnitSubType_HALOutput,
                                   kAudioUnitManufacturer_Apple, 0, 0};
    AudioComponent comp = AudioComponentFindNext(NULL, &d);
    if (!comp || AudioComponentInstanceNew(comp, &g_unit) != noErr) return -1;
    if (AudioUnitSetProperty(g_unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &g_dev,
                             sizeof g_dev) != noErr)
        return -1;

    AudioStreamBasicDescription f;
    memset(&f, 0, sizeof f);
    f.mSampleRate = st->rate;
    f.mFormatID = kAudioFormatLinearPCM;
    f.mFormatFlags = kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked;
    f.mChannelsPerFrame = st->channels;
    f.mBitsPerChannel = 32;
    f.mBytesPerFrame = 4 * st->channels;
    f.mFramesPerPacket = 1;
    f.mBytesPerPacket = f.mBytesPerFrame;
    if (AudioUnitSetProperty(g_unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 0, &f, sizeof f) !=
        noErr)
        return -1;

    AURenderCallbackStruct cb = {render_cb, NULL};
    if (AudioUnitSetProperty(g_unit, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0, &cb,
                             sizeof cb) != noErr)
        return -1;
    if (AudioUnitInitialize(g_unit) != noErr) return -1;

    AudioObjectPropertyAddress oa = {kAudioDeviceProcessorOverload, kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
    AudioObjectAddPropertyListener(g_dev, &oa, overload_cb, st);

    UInt32 actual = get_u32(g_dev, kAudioDevicePropertyBufferFrameSize, kAudioObjectPropertyScopeGlobal);
    UInt32 dev_lat = get_u32(g_dev, kAudioDevicePropertyLatency, kAudioObjectPropertyScopeOutput);
    UInt32 safety = get_u32(g_dev, kAudioDevicePropertySafetyOffset, kAudioObjectPropertyScopeOutput);
    UInt32 stream_lat = 0;
    AudioObjectPropertyAddress sa = {kAudioDevicePropertyStreams, kAudioObjectPropertyScopeOutput,
                                     kAudioObjectPropertyElementMain};
    AudioStreamID streams[8];
    sz = sizeof streams;
    if (AudioObjectGetPropertyData(g_dev, &sa, 0, NULL, &sz, streams) == noErr && sz >= sizeof(AudioStreamID))
        stream_lat = get_u32(streams[0], kAudioStreamPropertyLatency, kAudioObjectPropertyScopeGlobal);

    info->actual_period = actual;
    info->buffer_frames = actual;
    info->reported_latency_frames = dev_lat + safety + stream_lat + actual;
    atomic_store(&st->latency_frames, info->reported_latency_frames);
    snprintf(info->latency_detail, sizeof info->latency_detail,
             "{\"device_latency\":%u,\"safety_offset\":%u,\"stream_latency\":%u,\"io_buffer\":%u,"
             "\"note\":\"HAL-reported frames; converter and analogue path not included\"}",
             dev_lat, safety, stream_lat, actual);
    return 0;
}

int sxlat_backend_start(sxlat_state *st) {
    (void)st;
    return AudioOutputUnitStart(g_unit) == noErr ? 0 : -1;
}

void sxlat_backend_stop(sxlat_state *st, sxlat_backend_info *info) {
    (void)info;
    AudioOutputUnitStop(g_unit);
    AudioObjectPropertyAddress oa = {kAudioDeviceProcessorOverload, kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
    AudioObjectRemovePropertyListener(g_dev, &oa, overload_cb, st);
    AudioUnitUninitialize(g_unit);
    AudioComponentInstanceDispose(g_unit);
}
