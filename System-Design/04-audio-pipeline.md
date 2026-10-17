# 4. Audio Pipeline

## 4.1 Objective

The audio subsystem must improve ASR reliability without destroying speech evidence.

Input may be:

- WhatsApp Opus
- WAV
- MP3
- M4A
- phone-call recording

## 4.2 Pipeline

```text
Raw Audio
 ↓
Container/Codec Validation
 ↓
Format Normalization
 ↓
Channel/Sample Rate Normalization
 ↓
Voice Activity Detection
 ↓
Speech/Non-speech Segmentation
 ↓
Noise Estimation
 ↓
Selective Denoising
 ↓
Optional Dereverberation
 ↓
Optional Speech Enhancement
 ↓
Loudness/Gain Normalization
 ↓
Clipping Detection
 ↓
Quality Assessment
 ↓
ASR
```

## 4.3 Preserve original

Never mutate the original audio.

Store:

- original artifact
- normalized artifact
- processed artifact
- preprocessing metadata

This allows debugging and A/B evaluation.

## 4.4 Quality analyzer

Recommended fields:

- duration_ms
- sample_rate
- channels
- codec
- speech_ratio
- estimated_snr_db
- clipping_detected
- peak_level
- noise_level
- silence_ratio
- quality_class

Quality classes:

- GOOD
- ACCEPTABLE
- DEGRADED
- POOR
- UNUSABLE

## 4.5 Selective preprocessing

Do not assume denoising always improves ASR.

Decision example:

```text
SNR high
→ normalization only

SNR medium
→ mild denoise

SNR low + speech clear
→ stronger enhancement

speech ratio extremely low
→ ask for another recording / block
```

The exact thresholds should be configuration, not hard-coded business logic.

## 4.6 VAD

VAD should identify speech segments and remove long non-speech regions.

Do not aggressively trim internal pauses because pauses can be useful for interpretation.

## 4.7 Noise types to test

Synthetic evaluation should include:

- forklift
- grinder
- truck engine
- shop chatter
- fan noise
- street traffic
- reverberant warehouse
- wind
- intermittent impact sounds

## 4.8 Audio evaluation

Run the same semantic test on:

1. clean audio
2. noisy audio
3. noisy + preprocessing

Compare:

- ASR error
- entity accuracy
- quantity accuracy
- semantic task success

This demonstrates whether preprocessing actually contributes value.
