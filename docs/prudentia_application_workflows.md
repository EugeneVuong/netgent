# Prudentia — Application Workflow Details

Extracted from: Philip et al., *"Prudentia: Findings of an Internet Fairness Watchdog"*,
ACM SIGCOMM 2024. DOI: [10.1145/3651890.3672229](https://doi.org/10.1145/3651890.3672229)
(open PDF: [justinesherry.com/papers/philip-sigcomm2024.pdf](https://www.justinesherry.com/papers/philip-sigcomm2024.pdf)).
Live results: <https://www.internetfairness.net>. Testbed code is open-sourced by the authors.

This file summarizes, per application, **what the client actually does, for how long,
and how it is automated** — the information needed to reproduce these workflows
(e.g. as NetGent workflow JSONs).

## Testbed context (§3.1)

- **Topology**: dumbbell; two clients simultaneously access two live, deployed
  Internet services. All traffic passes through a **BESS software switch** that
  emulates the bottleneck (link speed, queue size, added delay). Everything past
  the access link travels unmodified Internet paths to the real services.
- **Bandwidth settings**: 8 Mbps ("highly-constrained") and 50 Mbps
  ("moderately-constrained") bottleneck.
- **RTT**: normalized to **50 ms** for all services (delay added at the switch;
  multi-flow services normalized on their first flow).
- **Queue**: drop-tail FIFO, ~**4×BDP** (BESS rounds to the nearest power of two).
- **Hygiene**: wired clients, no artificial loss/reordering; experiments with
  >0.05% packet loss external to the testbed are discarded; solo runs detect
  upstream throttling; trials run round-robin with >12 min between experiments
  on the same pair.

## Experiment shape (§3.4)

- **Duration: 10 minutes per experiment**; the **first and last 2 minutes are
  ignored** (the middle 6 minutes are analyzed).
- **Trials**: minimum **10 trials** per contender/incumbent pair, extended in
  batches of 10 up to **30 trials** until the 95% CI of the median is within
  ±0.5 Mbps (8 Mbps setting) or ±1.5 Mbps (50 Mbps setting).
- **Scale**: 12 services ≈ 80 pairs × 10 trials × 2 network settings ≈ 13+ days
  per full iteration (~20 hours for one trial of every pair).
- **Measurement period**: main dataset June–September 2023; RTC evaluation
  January 2024 (testbed running continuously since 2022).

## Client automation ("Application Fidelity", §3.3)

- Clients are driven by **Google Chrome controlled by Selenium** — *not*
  command-line tools and *not* headless mode, because both change application
  behavior (different TCP/QUIC connection sequences, lower ABR bitrate choices).
- **Netflix runs on Safari**: DRM prevents top quality on Chrome for macOS.
- **Cookies and browser cache are wiped between experiments** so every run
  fetches all application data over the network from a clean, repeatable state.
- Video clients require real rendering capacity: **Mac Mini desktops with a
  desktop-class GPU and a connected 4K monitor**. With a virtual display
  (`xvfb`), no GPU, or no native VP9 decode, clients silently request lower
  bitrates — invalidating the experiment.

## Services and workflows (Table 1, §3.2)

| Service | Category | What the client does | CCA | Max throughput | # concurrent flows | Notes |
|---|---|---|---|---|---|---|
| YouTube | Video on demand | Play Big Buck Bunny for 10 min | BBRv1.1 | 13 Mbps | 1 | 7 bitrates up to 4K; QUIC-based (not TCP) |
| Netflix | Video on demand | Play Big Buck Bunny for 10 min | NewReno | 8 Mbps | 4 | 6 bitrates up to 4K; run on Safari (DRM) |
| Vimeo | Video on demand | Play Big Buck Bunny for 10 min | BBR | 14 Mbps | 2 | 7 bitrates up to 4K |
| Dropbox | File transfer | Download a 10 GB random file | BBRv1.0 | ∞ | 1 | |
| Google Drive | File transfer | Download a 10 GB random file | BBRv3 | ∞ | 1 | |
| OneDrive | File transfer | Download a 10 GB random file | Cubic (extended) | ~45 Mbps | 1 | Cap is external to the testbed (seen even on a 1 Gbps link) |
| Mega | File transfer | Download a 10 GB random file | BBR | ∞ | 5 | Custom JS framework; downloads in batches of 5 chunks → bursty traffic; most contentious service tested |
| Google Meet | Real-time video (RTC) | Hold a video call | GCC | 1.5 Mbps | 1 | WebRTC-based |
| Microsoft Teams | Real-time video (RTC) | Hold a video call | Unknown | 2.6 Mbps | 1 | WebRTC-based |
| wikipedia.org | Web browsing | Load the page repeatedly (see below) | BBRv1.0 | ∞ | >5 | Mostly text, one or two images |
| news.google.com | Web browsing | Load the page repeatedly | BBRv3.0 | ∞ | >20 | Text with thumbnail images |
| youtube.com (front page) | Web browsing | Load the page repeatedly | BBRv3.0 | ∞ | >10 | Image-heavy (thumbnails); different CCA than YouTube's video servers |
| iPerf (BBRv1.0 / Cubic / NewReno) | Baseline | Bulk transfer | Linux 5.15 CCAs | ∞ | 1 | Baseline to compare app-level vs CCA-only testing |

"# flows" = connections carrying service workload data (e.g. video chunks) at the
same time. CCAs were determined via a CCA classifier and/or confirmed by engineers
at YouTube, Netflix, Google Drive, Dropbox, and Wikipedia.

### Per-category workflow details

**Video on demand (YouTube, Netflix, Vimeo)**
- Client plays the reference **Big Buck Bunny** video in a real browser for the
  full 10-minute experiment.
- The service's ABR algorithm freely selects bitrate (ladders up to 4K), so
  measured throughput is application-limited by the max bitrate (13 / 8 / 14 Mbps).
- Requires GPU + real 4K display, otherwise the ABR downshifts (§3.3).

**File transfer (Dropbox, Google Drive, OneDrive, Mega)**
- Client downloads **the same 10 GB randomly-generated file** hosted on each
  service, via the browser, for the 10-minute window (the file is large enough
  to never finish).
- Mega's client opens **5 concurrent flows** and downloads in batches of 5
  chunks, waiting for a whole batch before starting the next — producing bursty
  on/off traffic (Fig. 4, Observation 4).

**Real-time communication (Google Meet, Microsoft Teams)**
- Client participates in a live WebRTC video call for the experiment duration.
- Metrics collected (Table 2): **resolution** (majority height in px, e.g. 720p),
  **average FPS**, **freezes per minute** (WebRTC freeze definition: inter-frame
  gap > max(3·δ, δ+150 ms)), and **fraction of high-delay packets** (RTT > 190 ms,
  the ITU requirement for RTC).

**Web browsing (wikipedia.org, news.google.com, youtube.com) — §5.2**
- Metric: **page load time (PLT)** = time for 95% of the above-the-fold region
  to load, computed with Google's **SpeedIndex** technique on a 4K display.
- Procedure per trial: start the contender service; **after 30 s**, load the
  webpage in a **fresh Google Chrome instance**; repeat the page load **10
  times with a 45 s gap** between loads, each load in a new Chrome instance
  with cache and cookies wiped.
- Each trial repeated **≥5 times** → **≥50 data points** per service–webpage pair.

**Baseline (iPerf: BBRv1.0, Cubic, NewReno)**
- Single bulk-transfer flow per CCA on Linux 5.15, run like any other service,
  as the CCA-only comparison point.

## Headline findings (for context)

- Losing services achieve on average **72% of their max-min fair (MmF) share**
  (median 84%); even a service competing against itself averages only 88%.
- **Mega** is the most contentious service: competitors average 63% MmF beside
  it at 50 Mbps, some below 20% (OneDrive as low as 16%).
- **YouTube** — despite BBR — is among the *least* contentious: at 8 Mbps,
  competitors average **117%** of their MmF share against it (YouTube is
  generally sensitive, not aggressive).
- Competing traffic can **double webpage load times** at 50 Mbps and **triple
  them at 8 Mbps** (youtube.com: 8 s → 21 s median beside Mega/Netflix).
- CCA alone doesn't predict fairness (Mega and YouTube both use BBR variants);
  flow counts, ABR logic, and batching/burst patterns at the application layer
  drive outcomes.
