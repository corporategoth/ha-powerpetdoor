# Power Pet Door by High Tech Pet

[![Buy Me Coffee][buymecoffee]][donation]

[![Github Release][releases-shield]][releases]
[![Github Activity][commits-shield]][commits]
[![License][license-shield]][license]

[![hacs][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]

Custom component to allow control and monitoring of the Power Pet Door made by High Tech Pet.

This addon was NOT made by anyone affiliated with High Tech Pet, don't bug them about it!

## Install

1. Ensure you have HACS installed.
2. Click into `Integrations`, then select the three dots `...` in the top-right corner, and select `Custom Repositories`
3. Paste the guthub respository URL (`https://github.com/corporategoth/ha-powerpetdoor`) into the Repository field, and select `Integration` as a category, then press `ADD`.

Once the custom repository is installed into HACS, you should be able to click the button below to install this integration.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=corporategoth&repository=ha-powerpetdoor&category=integration)

Alternatively, you can follow these steps:

1. Click into `Integrations` under HACS, then click the `+ EXPLORE & DOWNLOAD REPOSITORIES` button in the lower-right corner.
1. Search for `Power Pet Door`, and click it.
1. Click the `DOWNLOAD` button in the lower-right corner, then click `DOWNLOAD` in the dialog box that appears.

## Manual Installation

1. Copy the `powerpetdoor` directory from `custom_components` in this repository into the `custom_components` directory under your Home Assistant's configuration directory.
1. Restart your Home Assistant.

**NOTE**: Installing manually means you will also have to upgrade manually.

## Setup

Click on the button below to add the integration automatically.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=powerpetdoor)

Alternatively, you can follow these steps:

1. Install this integration.
1. Navigate to the Home Assistant Integrations (`Settings` -> `Devices & Services`).
1. Click the `+ ADD INTEGRATION` button in the lower right-hand corner.
1. Search for Power Pet Door, and select it.

## Configuration

You can go to the Integrations page and add a Power Pet Door integration.

| Option | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| name | No | Power Pet Door | A pretty name for your Power Pet door entity |
| host | Yes |  | The host name or IP address of your Power Pet Door |
| port | No | 3000 | The port of your Power Pet Door |
| timeout | No | 10.0 | Time out on attempting to connect to your Power Pet Door (seconds) |
| reconnect | No | 5.0 | How long to wait between retrying to connect to your Power Pet Door if disconnected (seconds) |
| keep_alive | No | 30.0 | How often will we send a PING keep alive message to the Power Pet Door (seconds) |
| refresh | No | 300.0 | How often we pull the configuration settings from the Power Pet Door (seconds) |
| update | No |  | How often we update the current door position (seconds) |

## Entities

| Entity                         | Entity Type | Description                                                                                      |
|--------------------------------|-------------|--------------------------------------------------------------------------------------------------|
| `Door`                         | `Cover`     | The main control for the door itself.  Acts like a shutter entity.                               |
| `Auto`                         | `Switch`    | Enable or disable the door sensors based on a schedule setup in the Power Pet Door app.          |
| `Battery`                      | `Sensor`    | Display the current charge of the battery, if one is attached.                                   |
| `Cycle`                        | `Button`    | A button to perform the open / close cycle (or close the door if it's holding open).             |
| `Inside Sensor`                | `Switch`    | Enable or disable detection of a dog collar from the inside of the door.                         |
| `Outside Sensor`               | `Switch`    | Enable or disbale detection of a dog collar from the outside of the door.                        |
| `Power`                        | `Switch`    | Turn on or off the pet door (WiFi will stay enabled).  Disables ALL buttons, and door operation. |
| `Outside Safety Lock`          | `Switch`    | Always allow the pet to come inside, ignoring your schedule.                                     |
| `Pet Proximity Keep Open`      | `Switch`    | Keep the pet door open if the pet remains in proximity of the door.                              |
| `Auto Retract`                 | `Switch`    | Automatically retract (open) the door if it detects an obstruction while closing.                |
| `Latency`                      | `Sensor`    | The time it's taking for Home Assistant to communicate to the Power Pet Door (round trip).       |
| `Total Open Cycles`            | `Sensor`    | Total number of times the door has been opened.                                                  |
| `Total Auto-Retracts`          | `Sensor`    | Total number of times the door re-opened itself due to a detected obsctuction.                   |
| `Hold Time`                    | `Number`    | Amount of time (in seconds) to hold the door open during the open/close cycle.                   |
| `Sensor Trigger Voltage`       | `Number`    | Voltage required to trigger the sensor to open the door (based on signal strength).              |
| `Sleep Sensor Trigger Voltage` | `Number`    | Voltage required to trigger the sensor to open the door (based on signal strength) while off.    |
| `Notify Inside On`             | `Switch`    | Notify when your pet goes outside.                                                               |
| `Notify Inside Off`            | `Switch`    | Notify when your pet tries to go outside, but the Inside sensor is off.                          |
| `Notify Outside On`            | `Switch`    | Notify when your pet comes inside.                                                               |
| `Notify Outside Off`           | `Switch`    | Notify when your pet tries to come inside, but the Outside sensor is off.                        |
| `Notify Low Battery`           | `Switch`    | Notify when the door's battery is low.                                                           |
| `Connection`                   | `Switch`    | Control the Home Assistant connection to the Power Pet Door. Turn off to allow the mobile app to connect (only one client can connect at a time). |
| `Timezone`                     | `Select`    | Configure the timezone on the Power Pet Door device. Disabled by default.                        |
| `Inside Schedule`              | `Schedule`  | The schedule for the automatic enabling/disabling of the Inside Sensor. Can be viewed via entity attributes and updated via service. |
| `Outside Schedule`             | `Schedule`  | The schedule for the automatic enabling/disabling of the Outside Sensor. Can be viewed via entity attributes and updated via service. |

**Note:** The Power Pet Door only supports a single network connection at a time. If you need to use the official mobile app, turn off the `Connection` switch first. Similarly, if Home Assistant cannot connect, ensure the mobile app is closed.


## Attributes

| Entity    | Attribute             | Type        | Description                                                                                                                                                                                                          |
|-----------|-----------------------|-------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `Door`    | `door_status`         | `string`    | The raw door status as reported by the door itself. This will be one of `DOOR_IDLE`, `DOOR_CLOSED`, `DOOR_HOLDING`, `DOOR_KEEPUP`, `DOOR_SLOWING`, `DOOR_CLOSING_TOP_OPEN`, `DOOR_RISING`, `DOOR_CLOSING_MID_OPEN`). |
| `Door`    | `current_position`    | `number`    | The position of the door (as a 'percentage open').  This will only ever show 0, 33, 66 or 100.                                                                                                                       |
| `Battery` | `battery_discharging` | `boolean`   | Whether the battery is draining (ie. the power is disconnected).                                                                                                                                                     |
| `Battery` | `battery_charging`    | `boolean`   | Whether the battery is charging (ie. power is connected).                                                                                                                                                            |
| `Latency` | `host`                | `string`    | The IP address (or host name) of the Power Pet Door.                                                                                                                                                                 |
| `Latency` | `port`                | `number`    | The TCP port of the Power Pet Door.                                                                                                                                                                                  |
| `Latency` | `hw_version`          | `string`    | The hardware revision of the Power Pet Door device.                                                                                                                                                                  |
| `Latency` | `sw_version`          | `string`    | The firmware revision installed on the Power Pet Door device.                                                                                                                                                        |
| `*`       | `last_change`         | `timestamp` | The last time the state changed.                                                                                                                                                                                     |
| `*`       | `device_class`        | `string`    | The device class the entity presents as.                                                                                                                                                                             |
| `*`       | `state_class`         | `string`    | The type of sensor this is (should always be `measurement`).                                                                                                                                                         |
| `*`       | `unit_of_measurement` | `string`    | The unit measured by this sensor.                                                                                                                                                                                    |
| `Inside Schedule` / `Outside Schedule` | `schedule_entries` | `list` | Human-readable schedule entries formatted as "Mon, Wed, Fri: 06:00-20:00" |
| `Inside Schedule` / `Outside Schedule` | `schedule_count` | `number` | Number of active schedule entries |

## Viewing and Editing Schedules

### Viewing Schedules

The Power Pet Door integration provides several ways to view the current schedule:

#### Method 1: Custom Lovelace Card (Recommended)
The integration includes a visual schedule card with editing capabilities:
1. Add the resource to Home Assistant (see [Schedule Card Setup](#schedule-card-setup) below)
2. Add the `powerpetdoor-schedule-card` to your dashboard
3. View and edit schedules with a visual weekly calendar

#### Method 2: Entity Detail Page
1. Navigate to **Settings** → **Devices & Services**
2. Find your Power Pet Door device
3. Click on the **Inside Schedule** or **Outside Schedule** entity
4. View the schedule state and attributes, including:
   - `schedule_entries`: Human-readable list of schedule times (e.g., "Mon, Wed, Fri: 06:00-20:00")
   - `schedule_count`: Number of active schedule entries
   - `last_change`: When the schedule was last updated

#### Method 3: Developer Tools
1. Go to **Developer Tools** → **States**
2. Search for `schedule.power_pet_door_inside_schedule` or `schedule.power_pet_door_outside_schedule`
3. View the entity state and all attributes

#### Method 4: Entity Attributes
Schedule entities include readable attributes:
- `schedule`: Machine-readable schedule data (days with time ranges)
- `schedule_entries`: Array of formatted schedule strings showing days and time windows
- `schedule_count`: Total number of active schedule entries

### Editing Schedules

#### Method 1: Custom Lovelace Card (Recommended)

The easiest way to edit schedules is using the included visual schedule card:

1. Add the card to your dashboard (see [Schedule Card Setup](#schedule-card-setup) below)
2. Click **Edit** on the card to enter edit mode
3. Click on any day column to add a new time slot
4. Click on existing time slots to modify or delete them
5. Click **Save** to sync changes to the device

The card provides a visual weekly calendar that makes it easy to see and modify your schedule at a glance.

#### Method 2: Using the Mobile App

You can also edit schedules using the official Power Pet Door mobile app. The integration will automatically fetch the updated schedule on the next refresh (default: every 5 minutes).

**Note**: The mobile app has a caching bug where it displays its own cached schedule rather than reading from the device. While this integration will correctly show schedule changes made via the app, the app may not reflect changes made through Home Assistant. The device itself always has the correct schedule - only the app's display is incorrect.

#### Method 3: Using the Service (Advanced)

For automations or programmatic updates, use the `powerpetdoor.update_schedule` service:

```yaml
service: powerpetdoor.update_schedule
target:
  entity_id: schedule.power_pet_door_inside_schedule
data:
  schedule:
    monday:
      - from: "06:00:00"
        to: "20:00:00"
    tuesday:
      - from: "06:00:00"
        to: "20:00:00"
```

The schedule format uses weekday names as keys, with arrays of time windows containing `from` and `to` times in HH:MM:SS format. Multiple time windows per day are supported.

## Sample Card

Here is a sample lovelace card you could configure to control your Power Pet Door.

![Sample Card](images/petdoor-card.png)

```
type: vertical-stack
cards:
  - type: custom:mushroom-cover-card
    entity: cover.power_pet_door_door
    show_position_control: false
    show_buttons_control: true
    fill_container: false
    layout: horizontal
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.power_pet_door_button
      data: {}
  - type: horizontal-stack
    cards:
      - show_name: true
        show_icon: true
        type: button
        tap_action:
          action: toggle
        entity: switch.power_pet_door_inside_sensor
        name: Inside
      - show_name: true
        show_icon: true
        type: button
        tap_action:
          action: toggle
        entity: switch.power_pet_door_outside_sensor
        name: Outside
      - show_name: true
        show_icon: true
        type: button
        tap_action:
          action: toggle
        entity: switch.power_pet_door_auto
        name: Auto
      - show_name: true
        show_icon: true
        type: button
        tap_action:
          action: toggle
        entity: switch.power_pet_door_power
        name: Power
      - type: gauge
        entity: sensor.power_pet_door_battery
        name: Battery
        needle: false
  - type: conditional
    conditions:
      - condition: state
        entity: switch.power_pet_door_auto
        state: "on"
    card:
      type: custom:powerpetdoor-schedule-card
      entity: schedule.power_pet_door_inside_schedule
  - type: conditional
    conditions:
      - condition: state
        entity: switch.power_pet_door_auto
        state: "on"
    card:
      type: custom:powerpetdoor-schedule-card
      entity: schedule.power_pet_door_outside_schedule
```

### Schedule Card Setup

The Power Pet Door integration includes a custom Lovelace card for viewing and editing schedules with a visual weekly calendar.

**Installation:**

1. **Add the resource to Home Assistant:**
   - Go to **Settings** → **Dashboards** → click the three-dot menu → **Resources**
   - Click **Add Resource**
   - URL: `/local/community/ha-powerpetdoor/powerpetdoor-schedule-card.js` (if installed via HACS)
     - OR `/local/powerpetdoor-schedule-card.js` (if manually installed)
   - Resource type: **JavaScript Module**
   - Click **Create**

2. **Add the card to your dashboard:**
   - Edit your dashboard
   - Click **Add Card** → search for "Power Pet Door Schedule"
   - Or use manual YAML configuration:

```yaml
type: custom:powerpetdoor-schedule-card
entity: schedule.power_pet_door_inside_schedule
```

**Features:**
- **Visual Weekly Calendar**: Displays the entire week with time slots
- **Edit Mode**: Click "Edit" to add, modify, or remove time slots
- **Multiple Time Windows**: Supports multiple schedule entries per day
- **Click to Add**: In edit mode, click on any day column to add a new time slot
- **Click to Edit**: Click on existing time slots to modify times or delete them
- **WebSocket Integration**: Uses the `powerpetdoor/schedule/*` WebSocket commands for real-time updates

**Card Configuration Options:**

| Option | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| entity | Yes | | The schedule entity ID (e.g., `schedule.power_pet_door_inside_schedule`) |
| slot_color | No | `var(--primary-color, #03a9f4)` | Color for time slots |
| active_slot_color | No | `var(--warning-color, #ff9800)` | Color for currently active time slot |
| removal_color | No | `var(--error-color, #f44336)` | Color shown when shrinking/removing slots in edit mode |

**Example with custom colors:**

```yaml
type: custom:powerpetdoor-schedule-card
entity: schedule.power_pet_door_inside_schedule
slot_color: '#4caf50'
active_slot_color: 'var(--accent-color)'
removal_color: 'rgba(255, 0, 0, 0.7)'
```

## Credits

Big thanks to the authors of the [Envisalink component](https://home-assistant.io/integrations/envisalink), which I based a lot of the async networking code off of.

<!---->

***

[buymecoffee]: https://cdn.buymeacoffee.com/buttons/default-orange.png
[donation]: https://buymeacoffee.com/corporategoth
[commits-shield]: https://img.shields.io/github/commit-activity/y/corporategoth/ha-powerpetdoor.svg?style=for-the-badge
[commits]: https://github.com/corporategoth/ha-powerpetdoor/commits/main
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license]: https://github.com/corporategoth/ha-powerpetdoor/blob/main/LICENSE
[license-shield]: https://img.shields.io/github/license/corporategoth/ha-powerpetdoor.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40corporategoth-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/corporategoth/ha-powerpetdoor.svg?style=for-the-badge
[releases]: https://github.com/corporategoth/ha-powerpetdoor/releases
[user_profile]: https://github.com/corporategoth