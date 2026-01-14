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

When using `--auth`, you must set the following environment variables with your F1 TV account credentials:
- `F1_EMAIL`: Your F1 TV account email
- `F1_PASSWORD`: Your F1 TV account password

Example:
```bash
export F1_EMAIL="your.email@example.com"
export F1_PASSWORD="your_password"
python -m fastf1_livetiming save ./output.txt PitLaneTimeCollection DriverList TimingData --auth
```

The `--auth` option uses a browser-based login flow to retrieve a subscription token from F1 TV.
