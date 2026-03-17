# RADcast Optimized

`RADcast Optimized` is the default RADcast enhancement path.

Internal model id:
- `studio_v18`

Product label:
- `RADcast Optimized`

Tuning label written into outputs:
- `RADcast Optimized`

## Why this is the default

This path replaced the older `Studio v18` default after the Windows GPU lab runs consistently showed a closer match to the Adobe Podcast reference than:
- the older `Studio v18` defaults
- the `hftrim_k_aircut` postfilter-only branch
- the `step=600` restoration-only branch
- multiple `SGMSE` fine-tune branches
- `VoiceFixer`

The winning branch name from the lab was:
- `nara_chunk8_mild`

That branch combined:
1. chunked `nara_wpe` dereverberation
2. `Resemble Enhance`
3. the winning RADcast postfilter curve

## Signal chain

Default `RADcast Optimized` processing order:

1. Input conversion to mono WAV
2. No FFmpeg input prefilter by default
3. Chunked `nara_wpe` dereverberation
4. `Resemble Enhance`
5. RADcast Optimized FFmpeg postfilter
6. Final WAV/MP3 export

The default path does not use:
- the older built-in `WPE` dereverb path
- the older spectral-tail suppressor
- wet/dry blending
- the legacy `RADCAST_ENHANCE_PREFILTER`

## Default parameters

### Dereverb

Default dereverb method:
- `nara`

Default `nara_wpe` settings:
- chunk seconds: `8.0`
- overlap seconds: `1.0`
- taps: `6`
- delay: `2`
- iterations: `1`
- PSD context: `1`
- FFT size: `512`
- hop size: `128`

These values came from the best full-lecture result in the dereverb sweep. Later chunk/window refinements and hybrid tail-suppression branches did not beat them.

### Resemble Enhance

Default `Resemble Enhance` settings for `RADcast Optimized`:
- `nfe=32`
- `lambd=0.62`
- `tau=0.45`

### Input prefilter

Default:
- empty string

Meaning:
- no extra FFmpeg pre-clean is applied before dereverb on the optimized path

### Postfilter

Default postfilter:

```text
highpass=f=65,
equalizer=f=142:t=q:w=1.05:g=4.05,
equalizer=f=200:t=q:w=1.0:g=1.75,
equalizer=f=315:t=q:w=1.0:g=-0.55,
equalizer=f=455:t=q:w=1.0:g=-0.2,
equalizer=f=2350:t=q:w=1.0:g=-2.35,
equalizer=f=3000:t=q:w=1.0:g=-1.70,
equalizer=f=3850:t=q:w=1.0:g=-0.30,
deesser=i=0.045:m=0.18:f=0.5:s=o,
equalizer=f=5700:t=q:w=1.0:g=-1.40,
equalizer=f=6400:t=q:w=1.0:g=-1.20,
loudnorm=I=-20.75:TP=-1.5:LRA=8,
lowpass=f=7550
```

This is the postfilter that won the narrow Windows refinement sweep after the dereverb path was already fixed.

## Environment variables

The optimized path is controlled by these env vars:

- `RADCAST_DEFAULT_ENHANCEMENT_MODEL=studio_v18`
- `RADCAST_STUDIO_V18_TUNING_LABEL=RADcast Optimized`
- `RADCAST_STUDIO_V18_DEREVERB_METHOD=nara`
- `RADCAST_STUDIO_V18_ENHANCE_DEVICE=auto`
- `RADCAST_STUDIO_V18_PREFILTER=`
- `RADCAST_STUDIO_V18_NFE=32`
- `RADCAST_STUDIO_V18_LAMBD=0.62`
- `RADCAST_STUDIO_V18_TAU=0.45`
- `RADCAST_STUDIO_V18_NARA_CHUNK_SECONDS=8.0`
- `RADCAST_STUDIO_V18_NARA_OVERLAP_SECONDS=1.0`
- `RADCAST_STUDIO_V18_NARA_TAPS=6`
- `RADCAST_STUDIO_V18_NARA_DELAY=2`
- `RADCAST_STUDIO_V18_NARA_ITERATIONS=1`
- `RADCAST_STUDIO_V18_NARA_PSD_CONTEXT=1`
- `RADCAST_STUDIO_V18_POSTFILTER=<see above>`

Fallback variables for the older built-in dereverb path still exist:
- `RADCAST_STUDIO_V18_WPE_TAPS`
- `RADCAST_STUDIO_V18_WPE_DELAY`
- `RADCAST_STUDIO_V18_WPE_ITERATIONS`

Those are only used if `RADCAST_STUDIO_V18_DEREVERB_METHOD` is changed away from `nara`.

## Performance notes

- The optimized dereverb stage is CPU-bound and already relatively cheap.
- The slow stage is `Resemble Enhance`.
- On Apple Silicon helpers, the default optimized enhancement stage now stays on `cpu`.
- The macOS helper bootstrap installs `RADcast`, `resemble-enhance`, and `deepfilternet` first, then reapplies the known-good `resemble-enhance` Torch stack: `torch 2.1.1`, `torchaudio 2.1.1`, and `torchvision 0.16.1`.
- `RADcast Optimized` now runs in-process inside the long-lived helper/server process instead of spawning a fresh `radcast-studio-enhance` subprocess for every job.
- That means repeated jobs can reuse the loaded `Resemble` model through `radcast.services.resemble_safe.load_enhancer()`.
- On this Apple Silicon Mac, a real `6s` clip dropped from `28.7s` on the first in-process run to `11.7s` on the second run because the model stayed warm in memory.
- On Windows GPU helpers, `RADcast Optimized` should use `cuda` automatically when available.
- The stage-specific override is `RADCAST_STUDIO_V18_ENHANCE_DEVICE`.
- This specific Mac is still blocked from using `mps` reliably. The attempted Torch `2.10` Apple Silicon runtime produced a severe quality regression on the held-out lecture, so the helper now stays on the known-good CPU path until a validated MPS stack exists.

## Dependencies

`RADcast Optimized` requires:
- `resemble-enhance`
- `nara-wpe`
- `numpy`
- `scipy`
- `soundfile`
- `torchaudio`

The Linux install helper also installs `nara-wpe==0.0.11`.

## Code map

Primary implementation files:
- `/Users/rcd58/RADcast/src/radcast/constants.py`
- `/Users/rcd58/RADcast/src/radcast/services/enhance.py`
- `/Users/rcd58/RADcast/src/radcast/services/studio.py`
- `/Users/rcd58/RADcast/src/radcast/studio_cli.py`
- `/Users/rcd58/RADcast/src/radcast/models.py`
- `/Users/rcd58/RADcast/src/radcast/api.py`
- `/Users/rcd58/RADcast/src/radcast/static/ui.js`

## Lab provenance

The last important lab conclusions worth preserving:

- plain older `Studio v18` full-lecture score: `4.4837`
- `hftrim_k_aircut` full-lecture score: `0.7531`
- `nara_chunk8_mild` full-lecture score: `0.5204`

Interpretation:
- lower score is closer to the Adobe reference on the measured feature set
- `nara_chunk8_mild` was the best confirmed full-lecture result
- later chunk/window variants, hybrid spectral suppression, and tail-blend branches did not beat it

## Operational notes

- Existing projects may still point at a previously saved enhancement model.
- New projects default to `RADcast Optimized`.
- If the optimized model appears unavailable, first check that `nara_wpe` imports in the active RADcast environment.
