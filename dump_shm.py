#!/usr/bin/env python3
import os
import glob
import struct

def dump_shm():
    files = glob.glob('/dev/shm/squeezelite-*')
    if not files:
        print("No squeezelite shared memory found. Is Squeezelite running with -v?")
        return

    shm_file = files[0]
    print(f"Reading from: {shm_file}")

    try:
        size = os.path.getsize(shm_file)
        print(f"File size: {size} bytes")

        with open(shm_file, 'rb') as f:
            data = f.read(128)

            print("\n--- Raw Hex Dump (first 128 bytes) ---")
            for i in range(0, len(data), 16):
                chunk = data[i:i+16]
                hex_str = ' '.join(f'{b:02x}' for b in chunk)
                print(f"{i:03d}: {hex_str}")

            print("\n--- As 32-bit Integers (Little Endian) ---")
            ints = struct.unpack(f'<{len(data)//4}I', data)
            for i, val in enumerate(ints):
                print(f"Offset {i*4:02d}: {val} (0x{val:08x})")

            print("\n--- Trying to interpret the audio buffer ---")
            # Usually buf_size is around 8192 or 16384 samples.
            # If the file size is e.g. 32848, and there is a header,
            # then buffer size in bytes is probably size - header.
            # 32848 - 32 = 32816 bytes = 16408 int16 samples.

            # Let's peek at offsets 24 and 32 to see if they look like PCM data
            for offset in [24, 32, 40]:
                f.seek(offset)
                pcm_data = f.read(32)
                samples = struct.unpack('<16h', pcm_data)
                print(f"PCM samples at offset {offset}: {samples}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    dump_shm()