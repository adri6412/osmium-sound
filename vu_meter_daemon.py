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

class SqueezeliteVisualizer:
    def __init__(self):
        self.shm_file = self.find_shm_file()
        self.mmap_obj = None
        self.fd = None

        # We want to send 32 bars to the frontend
        self.num_bars = 32

        # Track the last known buffer index to detect playback state
        # instead of relying on the running boolean flag which may be incorrectly aligned.
        self.last_buf_index = -1
        self.same_index_count = 0

        # Buffer offset will be determined dynamically
        self.buffer_offset = None
        self.buf_size = 0

    def find_shm_file(self):
        """Find the squeezelite shared memory file in /dev/shm"""
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
            size = os.path.getsize(self.shm_file)
            self.mmap_obj = mmap.mmap(self.fd, size, access=mmap.ACCESS_READ)

            # Read buf_size to determine total expected size and validate struct alignment
            self.mmap_obj.seek(0)
            header = self.mmap_obj.read(12)
            sync, buf_size, buf_index = struct.unpack('<III', header)
            self.buf_size = buf_size

            # Autodetect 32-bit vs 64-bit alignment for time_t
            # buffer starts right after time_t updated.
            # 64-bit: 32 bytes header
            # 32-bit: 24 bytes header

            # The easiest way to determine offset is to check if size - offset == buf_size * 2 (s16_t)
            if size - 32 == buf_size * 2:
                self.buffer_offset = 32
                print("Detected 64-bit architecture shared memory (offset 32)")
            elif size - 24 == buf_size * 2:
                self.buffer_offset = 24
                print("Detected 32-bit architecture shared memory (offset 24)")
            else:
                # Fallback to standard 64-bit if sizes are weird
                print(f"Warning: Could not auto-detect offset. Size: {size}, buf_size: {buf_size}. Defaulting to 32.")
                self.buffer_offset = 32

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
            # We only need to reliably read buf_index (at offset 8)
            self.mmap_obj.seek(8)
            buf_index = struct.unpack('<I', self.mmap_obj.read(4))[0]

            # If buf_index hasn't changed for a few ticks, we consider it stopped/paused
            if buf_index == self.last_buf_index:
                self.same_index_count += 1
            else:
                self.same_index_count = 0
                self.last_buf_index = buf_index

            # If it hasn't changed for ~10 frames, send zeros
            if self.same_index_count > 10:
                return [0] * self.num_bars

            # If buf_index is very small, we might not have enough data to read a frame
            samples_to_read = 1024  # Read last 1024 interleaved samples (512 pairs)

            if buf_index < samples_to_read * 2: # 2 bytes per s16_t sample
                start_offset = self.buffer_offset
            else:
                start_offset = self.buffer_offset + (buf_index - (samples_to_read * 2))

            # Ensure we don't read past the file limit
            file_size = self.mmap_obj.size()
            if start_offset + (samples_to_read * 2) > file_size:
                # Re-connect or reset if size is weird
                return [0] * self.num_bars

            self.mmap_obj.seek(start_offset)
            raw_samples = self.mmap_obj.read(samples_to_read * 2)

            num_samples = len(raw_samples) // 2
            if num_samples == 0:
                return [0] * self.num_bars

            samples = struct.unpack(f'<{num_samples}h', raw_samples)

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

                # Boost RMS value artificially if it's very low, to make meter more responsive
                # Since digital volume control can make RMS tiny
                if rms <= 0:
                    percent = 0
                else:
                    # dB calculation
                    db = 20 * math.log10(rms / 32767.0)
                    # map -60dB -> 0%, 0dB -> 100%
                    percent = max(0, min(100, (db + 60) * (100/60)))

                    # Boost lower volumes non-linearly to make the visualizer more lively
                    if percent > 0:
                        percent = min(100, percent * 1.5)

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