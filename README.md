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
