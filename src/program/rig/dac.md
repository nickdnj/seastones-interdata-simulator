word_bits: 12              # the converter keeps the top 12 bits of each 16-bit code
range_v: 10.24             # full scale 0 to 10.24 V: 12-bit LSB 2.5 mV, 3 cents at 1 V/oct
output_hz: 2000            # the `analog` mode's converter output low-pass
strobe_hz: 1000            # the `strobed` mode's D/A update clock

The D/A model (ARCHITECTURE 5.2, 6.3, 6.4; MACH-3). Both word_bits and range_v are hypotheses
for RE-7 Q2, labelled as such. sxasm reads range_v for the pitch table (an ideal 16-bit
converter, so word_bits never changes the image); the engine reads every value
(`sx-render --rig-dac`, sx_config).

Developer note, not visitor copy. ARCHITECTURE 11.2 puts this file at content/rig/dac.md.
