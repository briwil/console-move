// Machinedrum speed test for the console.
//
// Loads your Machinedrum ROM, starts the emulated machine, then plays a simple beat into it and times how
// long the computer takes to make each bit of sound. If it makes sound faster than it plays, the Pi can run
// it live.
//
//   mdSpeedTest <rom.bin> [seconds] [out.wav]
//
// The result line says how many times faster than real time it ran. Above 1.0 means it keeps up; the console
// also needs room for its own work, so about 1.5 or more is what we want.
#include "mdLib/mddevice.h"
#include "mdLib/mdhardware.h"
#include "mdLib/mdromloader.h"
#include "mdLib/mdtypes.h"

#include "baseLib/filesystem.h"
#include "synthLib/plugin.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>

namespace
{
	using Clock = std::chrono::steady_clock;

	constexpr float g_rate = 44100.0f;
	constexpr size_t g_block = 256;

	double secondsSince(const Clock::time_point _t)
	{
		return std::chrono::duration<double>(Clock::now() - _t).count();
	}

	void writeWav(const std::string& _path, const std::vector<float>& _l, const std::vector<float>& _r)
	{
		FILE* f = std::fopen(_path.c_str(), "wb");
		if(!f)
			return;
		const uint32_t frames = static_cast<uint32_t>(_l.size());
		const uint32_t dataBytes = frames * 4;
		auto u32 = [&](const uint32_t _v) { std::fwrite(&_v, 4, 1, f); };
		auto u16 = [&](const uint16_t _v) { std::fwrite(&_v, 2, 1, f); };
		std::fwrite("RIFF", 1, 4, f); u32(36 + dataBytes); std::fwrite("WAVEfmt ", 1, 8, f);
		u32(16); u16(1); u16(2); u32(static_cast<uint32_t>(g_rate)); u32(static_cast<uint32_t>(g_rate) * 4);
		u16(4); u16(16);
		std::fwrite("data", 1, 4, f); u32(dataBytes);
		for(uint32_t i = 0; i < frames; ++i)
		{
			const int16_t l = static_cast<int16_t>(std::clamp(_l[i], -1.0f, 1.0f) * 32767.0f);
			const int16_t r = static_cast<int16_t>(std::clamp(_r[i], -1.0f, 1.0f) * 32767.0f);
			std::fwrite(&l, 2, 1, f);
			std::fwrite(&r, 2, 1, f);
		}
		std::fclose(f);
	}
}

int main(const int _argc, char** _argv)
{
	if(_argc < 2)
	{
		std::printf("usage: mdSpeedTest <rom.bin> [seconds] [out.wav]\n");
		return 1;
	}
	const double seconds = _argc > 2 ? std::atof(_argv[2]) : 30.0;
	const std::string wavPath = _argc > 3 ? _argv[3] : "";

	std::vector<uint8_t> rom;
	if(!baseLib::filesystem::readFile(rom, _argv[1]))
	{
		std::printf("Couldn't read %s\n", _argv[1]);
		return 1;
	}
	if(!md::RomLoader::isRomForModel(rom, md::MachineModel::Machinedrum))
	{
		std::printf("That file isn't the Machinedrum OS 1.63 ROM this emulator needs.\n");
		return 1;
	}

	synthLib::DeviceCreateParams params;
	params.romData = std::move(rom);
	params.romName = _argv[1];
	params.customData = md::deviceCustomData(md::MachineModel::Machinedrum);

	const auto created = Clock::now();
	auto device = std::make_unique<md::Device>(params);
	if(!device->isValid())
	{
		std::printf("The emulator didn't accept the ROM.\n");
		return 1;
	}
	synthLib::Plugin plugin(device.get(), [](synthLib::Device*) {});
	plugin.reserveMidiEventCapacity();
	plugin.setHostSamplerate(g_rate, g_rate);
	plugin.setBlockSize(g_block);

	std::array<float, g_block> inL{}, inR{};
	std::array<std::array<float, g_block>, 6> out{};
	const synthLib::TAudioInputs inputs{inL.data(), inR.data(), nullptr, nullptr};
	synthLib::TAudioOutputs outputs{};
	for(size_t c = 0; c < out.size(); ++c)
		outputs[c] = out[c].data();

	// ---- start-up: run until the firmware is ready to take MIDI (up to 60 s of sound)
	size_t bootFrames = 0;
	while(!device->getHardware().isFirmwareMidiReady() && bootFrames < static_cast<size_t>(g_rate * 60))
	{
		plugin.process(inputs, outputs, g_block, 120.0, 0.0, false);
		bootFrames += g_block;
	}
	// the firmware takes about 10 more seconds before the tracks make sound, so let it settle
	for(int i = 0; i < 2000; ++i)
	{
		plugin.process(inputs, outputs, g_block, 120.0, 0.0, false);
		bootFrames += g_block;
	}
	// A fresh machine's kit has no sounds on its tracks, so give the four tracks we play a TR machine each
	// (Machinedrum manual, appendix C: assign machine). Machine numbers: 16 TRX-BD, 17 TRX-SD, 22 TRX-CH,
	// 23 TRX-OH. Tracks 1, 2, 9 and 10 are the ones notes 36, 38, 50 and 52 play.
	const std::array<std::array<uint8_t, 2>, 4> machines{{{0, 16}, {1, 17}, {8, 22}, {9, 23}}};
	for(const auto& m : machines)
	{
		synthLib::SMidiEvent ev(synthLib::MidiEventSource::Host);
		ev.sysex = {0xf0, 0x00, 0x20, 0x3c, 0x02, 0x00, 0x5b, m[0], m[1], 0x00, 0xf7};
		plugin.addMidiEvent(ev);
		for(int i = 0; i < 40; ++i)
		{
			plugin.process(inputs, outputs, g_block, 120.0, 0.0, false);
			bootFrames += g_block;
		}
	}
	const double bootWall = secondsSince(created);
	std::printf("Start-up: %.1f s of machine time took %.1f s\n", bootFrames / g_rate, bootWall);
	if(!device->getHardware().isFirmwareMidiReady())
		std::printf("Warning: the firmware never said it was ready for MIDI.\n");

	// ---- the beat: 120 BPM sixteenths. Default Machinedrum notes: BD 36, SD 38, CH 50, OH 52.
	const double budget = g_block / g_rate;
	const size_t frames = static_cast<size_t>(seconds * g_rate);
	const size_t sixteenth = static_cast<size_t>(g_rate * 60.0 / 120.0 / 4.0);
	std::vector<float> wavL, wavR;
	if(!wavPath.empty())
	{
		wavL.reserve(frames);
		wavR.reserve(frames);
	}

	size_t pos = 0, late = 0, blocks = 0;
	double worst = 0.0;
	double peak = 0.0, sumSq = 0.0;
	const auto start = Clock::now();
	while(pos < frames)
	{
		for(size_t f = pos; f < pos + g_block; ++f)
		{
			if(f % sixteenth)
				continue;
			const size_t step = (f / sixteenth) % 16;
			const auto offset = static_cast<uint32_t>(f - pos);
			auto hit = [&](const uint8_t _note, const uint8_t _vel)
			{
				plugin.addMidiEvent({synthLib::MidiEventSource::Host, synthLib::M_NOTEON, _note, _vel, offset});
			};
			if(step % 4 == 0) hit(36, 120);
			if(step == 4 || step == 12) hit(38, 110);
			hit(step == 14 ? 52 : 50, step % 2 ? 70 : 100);
		}
		const auto t = Clock::now();
		plugin.process(inputs, outputs, g_block, 120.0, 0.0, false);
		const double took = secondsSince(t);
		worst = std::max(worst, took);
		if(took > budget)
			++late;
		++blocks;
		for(size_t i = 0; i < g_block; ++i)
		{
			const float l = out[0][i], r = out[1][i];
			peak = std::max(peak, static_cast<double>(std::max(std::fabs(l), std::fabs(r))));
			sumSq += 0.5 * (l * l + r * r);
			if(!wavPath.empty())
			{
				wavL.push_back(l);
				wavR.push_back(r);
			}
		}
		pos += g_block;
	}
	const double wall = secondsSince(start);
	const double audio = pos / g_rate;

	std::printf("Played %.1f s of beat in %.1f s\n", audio, wall);
	std::printf("Worst block: %.2f ms (each block has %.2f ms); %zu of %zu blocks were late\n",
		worst * 1000.0, budget * 1000.0, late, blocks);
	std::printf("Sound level: peak %.3f, average %.4f%s\n", peak, std::sqrt(sumSq / pos),
		peak < 1e-4 ? "  (silent: no sound came out)" : "");
	std::printf("RESULT: %.2fx real time\n", audio / wall);

	if(!wavPath.empty())
	{
		writeWav(wavPath, wavL, wavR);
		std::printf("Wrote %s\n", wavPath.c_str());
	}
	return 0;
}
