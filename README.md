# FastF1 livetiming module

A slightly modified version of FastF1 livetiming module, for OpenF1.

## Quick Start

### Installation

To install the Python package, run:

```
pip install -e .
```

### Usage

To record live F1 data topics such as `PitLaneTimeCollection`, `DriverList`, and `TimingData`, and save it to `./output.txt`, execute:

```
python -m fastf1_livetiming save ./output.txt PitLaneTimeCollection DriverList TimingData
```

#### Authentication (--auth)

If you need to use authenticated access to the F1 live timing API, use the `--auth` flag:

```
python -m fastf1_livetiming save ./output.txt PitLaneTimeCollection DriverList TimingData --auth
```

When using `--auth`, you must set the `F1_TOKEN` environment variable with your F1 authentication token.

To get your token, follow the instructions here: https://github.com/SoMuchForSubtlety/f1viewer/wiki/Getting-your-subscription-token

Note: The F1 token is usually valid for 4 days, after which you'll need to obtain a new one.

Example:

```bash
export F1_TOKEN="your_f1_token_here"
python -m fastf1_livetiming save ./output.txt PitLaneTimeCollection DriverList TimingData --auth
```
