# Baby Tracker for Home Assistant

This custom component integrates the Baby Tracker app data with Home Assistant, allowing you to monitor and update your baby's activities through Home Assistant.

## Features

- **Automatic Syncing**: Synchronizes with the Baby Tracker servers to fetch the latest data
- **Sensor Data**: Creates sensors for feeding, diaper changes, temperature, and more
- **Service Calls**: Allows adding new records through Home Assistant service calls

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add the URL: `https://github.com/yourusername/home-assistant-baby-tracker`
6. Select "Integration" as the category
7. Click "Add"
8. Find and install "Baby Tracker" in HACS

### Manual Installation

1. Download the latest release from this repository
2. Create a folder called `baby_tracker` in your `/config/custom_components/` directory
3. Copy all files from this repository into that folder
4. Restart Home Assistant

## Configuration

### Through the UI

1. Go to Configuration > Integrations
2. Click on the "+ Add Integration" button
3. Search for "Baby Tracker"
4. Enter your Baby Tracker email and password

### Through YAML (legacy method)

```yaml
# Example configuration.yaml entry
baby_tracker:
  email: your-email@example.com
  password: your-password
  scan_interval: 15  # Optional: minutes between updates (default: 15)
```

## Available Sensors

After setting up the integration, the following sensors will be created for each baby:

- Last Feeding (time and type)
- Last Diaper (time and type)
- Temperature (latest reading)
- Feeding Count (last 7 days)
- Nursing Minutes (last 7 days)
- Bottle Oz (last 7 days)
- Bottle ML (last 7 days)
- Diaper Count (last 7 days)
- Poopy Count (last 7 days)
- Wet Count (last 7 days)

## Service Calls

### Add Diaper Change

```yaml
service: baby_tracker.add_diaper
data:
  pee: true
  poo: false
  pee_color: 0  # Optional (0-5)
  poo_color: 0  # Optional (0-5)
  texture: 0    # Optional (0-5)
  amount: 2     # Optional (0-5)
  note: "Optional note"
```

### Add Nursing Session

```yaml
service: baby_tracker.add_nursing
data:
  left_duration: 15  # Minutes
  right_duration: 10  # Minutes
  both_duration: 0   # Minutes
  finish_side: "Left"  # "Left", "Right", or "Both"
  note: "Optional note"
```

### Add Formula Feeding

```yaml
service: baby_tracker.add_formula
data:
  amount: 120  # Amount in ml (or oz if is_english_measure is true)
  is_english_measure: false  # Optional (default: false)
  note: "Optional note"
```

### Add Pumped Milk

```yaml
service: baby_tracker.add_pumped
data:
  amount: 90  # Amount in ml (or oz if is_english_measure is true)
  is_english_measure: false  # Optional (default: false)
  note: "Optional note"
```

### Add Temperature

```yaml
service: baby_tracker.add_temperature
data:
  temperature: 98.6
  is_fahrenheit: true  # Optional (default: true)
  note: "Optional note"
```

### Manually Sync

```yaml
service: baby_tracker.sync
```

## Automation Examples

### Add a Diaper Change Through Voice Assistant

```yaml
automation:
  - alias: "Record Diaper Change"
    trigger:
      platform: homeassistant
      event: start
    action:
      - service: baby_tracker.add_diaper
        data:
          pee: true
          poo: true
          note: "Recorded via automation"
```

### Daily Report Notification

```yaml
automation:
  - alias: "Daily Baby Report"
    trigger:
      platform: time
      at: "20:00:00"
    action:
      - service: notify.mobile_app
        data:
          title: "Daily Baby Summary"
          message: >
            Today's totals:
            - Feedings: {{ states('sensor.baby_name_feedings') }}
            - Diapers: {{ states('sensor.baby_name_diapers') }}
            - Nursing minutes: {{ states('sensor.baby_name_nursing_minutes') }}
```

## Troubleshooting

- **Connection Issues**: If you're having trouble connecting, check that your Baby Tracker credentials are correct
- **Data Not Updating**: Try manually triggering a sync with the `baby_tracker.sync` service
- **Missing Data**: Make sure the database path is writeable by Home Assistant

## Privacy Notice

This integration stores your Baby Tracker credentials locally to sync with the Baby Tracker servers. No data is sent to third parties.

## Support

For issues and feature requests, please submit them through the GitHub repository's issue tracker.
