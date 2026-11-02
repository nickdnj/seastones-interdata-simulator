/* sx_math.h: deterministic elementary functions for the render path (VS-30, ADR-010).
 *
 * Golden renders must be bit-identical on Mac arm64 and Linux x86-64, so nothing in the render
 * path calls libm: these use only IEEE add, multiply and divide (contraction into FMA is off in
 * the build), in a fixed order.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_MATH_H
#define SX_MATH_H

/* 2^x for |x| < 1000. Range reduction to the nearest integer n and r in [-0.5, 0.5], a fixed
 * degree-11 polynomial for 2^r (relative error below 1e-15, far inside ADR-010's 0.01 cent =
 * 5.8e-6), and 2^n built exactly from the exponent bits. */
double sx_exp2(double x);

/* sin(2 pi p) for p in cycles (any finite value; reduced to the nearest quarter). Fixed
 * odd polynomial; error below 1e-13, far below ADR-010's -100 dB THD. */
double sx_sin_cycles(double p);

#endif
