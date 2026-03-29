#!/usr/bin/env python3
import asyncio
import mmap
import os
import struct
import json
import websockets
import math
import time
import glob

# Squeezelite shared memory structure for visualizer (-v)
# Source reference from Squeezelite output.c:
# struct vis_t {
#     u32_t sync;      // 0
#     u32_t buf_size;  // 4
#     u32_t buf_index; // 8
#     bool running;    // 12
#     u32_t rate;      // 16
#     time_t updated;  // 24 (on 64-bit systems)
#     s16_t buffer[vis_mmap_buffer_size]; // size varies (usually 4096 or 8192)
# };

# For our 64bit system layout (Python struct packing):
# I = unsigned int (4)
# ? = bool (1)
# 3x padding (3) to align 'rate' to 4-byte boundary
# I = rate (4)
# 4x padding (4) to align 'updated' to 8-byte boundary
# q = time_t (8)
# We will just map the header to find running state and buf_index,
# then read the raw PCM values (s16_t, 2 bytes each) interleaved L/R.

HEADER_FMT = '<III?3xI4xq'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

class SqueezeliteVisualizer:
    def __init__(self):
        self.shm_file = self.find_shm_file()
        self.mmap_obj = None
        self.fd = None

        # We want to send 32 bars to the frontend
        self.num_bars = 32

    def find_shm_file(self):
        """Find the squeezelite shared memory file in /dev/shm"""
        # Usually named /dev/shm/squeezelite-xxx
        files = glob.glob('/dev/shm/squeezelite-*')
        if files:
            print(f"Found Squeezelite shared memory at: {files[0]}")
            return files[0]
        return None

    def connect(self):
        """Connect to the shared memory file"""
        if not self.shm_file:
            self.shm_file = self.find_shm_file()

        if not self.shm_file or not os.path.exists(self.shm_file):
            return False

        try:
            self.fd = os.open(self.shm_file, os.O_RDONLY)
            # Map the entire file
            size = os.path.getsize(self.shm_file)
            self.mmap_obj = mmap.mmap(self.fd, size, access=mmap.ACCESS_READ)
            return True
        except Exception as e:
            print(f"Error opening shared memory: {e}")
            self.disconnect()
            return False

    def disconnect(self):
        if self.mmap_obj:
            self.mmap_obj.close()
            self.mmap_obj = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read_audio_data(self):
        """Read current PCM data and calculate visualizer levels"""
        if not self.mmap_obj:
            if not self.connect():
                return None

        try:
            # Read header
            self.mmap_obj.seek(0)
            header_data = self.mmap_obj.read(HEADER_SIZE)
            sync, buf_size, buf_index, running, rate, updated = struct.unpack(HEADER_FMT, header_data)

            if not running:
                # Music is stopped/paused
                return [0] * self.num_bars

            # If buf_index is very small, we might not have enough data to read a frame
            samples_to_read = 1024  # Read last 1024 interleaved samples (512 pairs)

            if buf_index < samples_to_read * 2: # 2 bytes per s16_t sample
                # Wrap around logic could be implemented, but for simple VU meter, just skip frame
                start_offset = HEADER_SIZE
            else:
                start_offset = HEADER_SIZE + (buf_index - (samples_to_read * 2))

            self.mmap_obj.seek(start_offset)
            raw_samples = self.mmap_obj.read(samples_to_read * 2)

            # Unpack as signed 16-bit integers
            num_samples = len(raw_samples) // 2
            samples = struct.unpack(f'<{num_samples}h', raw_samples)

            # Separate into Left and Right channels (interleaved)
            # samples[0::2] is Left, samples[1::2] is Right
            # For a combined VU meter (like typical single-bar displays), we can just average L/R
            # or calculate RMS of both combined.

            # Simple downsampling/bucketing to num_bars
            levels = []
            samples_per_bar = max(1, num_samples // self.num_bars)

            for i in range(self.num_bars):
                start_idx = i * samples_per_bar
                end_idx = start_idx + samples_per_bar

                # Calculate RMS (Root Mean Square) for the chunk
                chunk = samples[start_idx:end_idx]
                if not chunk:
                    levels.append(0)
                    continue

                sum_sq = sum(float(x)**2 for x in chunk)
                rms = math.sqrt(sum_sq / len(chunk))

                # Convert to a 0-100 percentage
                # Max s16_t is 32767.
                # We use a non-linear scaling (log-like) to make lower volumes visible
                if rms <= 0:
                    percent = 0
                else:
                    # dB calculation (roughly)
                    db = 20 * math.log10(rms / 32767.0)
                    # map -60dB -> 0%, 0dB -> 100%
                    percent = max(0, min(100, (db + 60) * (100/60)))

                levels.append(int(percent))

            return levels

        except Exception as e:
            print(f"Error reading shared memory: {e}")
            self.disconnect()
            return None


async def vu_meter_server(websocket, path):
    """WebSocket handler to stream VU meter data"""
    print(f"Client connected to VU meter stream")
    viz = SqueezeliteVisualizer()

    # Send empty data initially
    empty_data = [0] * viz.num_bars

    try:
        while True:
            # 30 fps = ~0.033s sleep
            await asyncio.sleep(0.033)

            levels = viz.read_audio_data()

            if levels is None:
                # Shared memory not found or error, send zeros
                await websocket.send(json.dumps({"levels": empty_data, "active": False}))
                # Poll slower if not active
                await asyncio.sleep(1.0)
                continue

            # Send real data
            payload = json.dumps({"levels": levels, "active": any(l > 0 for l in levels)})
            await websocket.send(payload)

    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
    finally:
        viz.disconnect()


async def main():
    print("Starting Squeezelite VU Meter Daemon on ws://0.0.0.0:9001")
    # Bind to all interfaces on port 9001
    server = await websockets.serve(vu_meter_server, "0.0.0.0", 9001)
    await server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")