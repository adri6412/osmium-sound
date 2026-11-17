/* The fixed-size types the kernel's uapi headers expect, for the emscripten
 * build of the kiosk interface (linux/input.h is copied from the kernel). */
#pragma once
#include <stdint.h>
typedef uint8_t __u8;  typedef int8_t __s8;
typedef uint16_t __u16; typedef int16_t __s16;
typedef uint32_t __u32; typedef int32_t __s32;
typedef uint64_t __u64; typedef int64_t __s64;
typedef __u16 __le16; typedef __u32 __le32; typedef __u64 __le64;
typedef __u16 __be16; typedef __u32 __be32; typedef __u64 __be64;
