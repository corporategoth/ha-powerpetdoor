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
| `Inside Schedule`              | `Schedule`  | The schedule for the automatic enabling/disabling of the Inside Sensor. Can be viewed via entity attributes and updated via service. |
| `Outside Schedule`             | `Schedule`  | The schedule for the automatic enabling/disabling of the Outside Sensor. Can be viewed via entity attributes and updated via service. |


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

#### Method 1: Entity Detail Page
1. Navigate to **Settings** → **Devices & Services**
2. Find your Power Pet Door device
3. Click on the **Inside Schedule** or **Outside Schedule** entity
4. View the schedule state and attributes, including:
   - `schedule_entries`: Human-readable list of schedule times (e.g., "Mon, Wed, Fri: 06:00-20:00")
   - `schedule_count`: Number of active schedule entries
   - `last_change`: When the schedule was last updated

#### Method 2: Developer Tools
1. Go to **Developer Tools** → **States**
2. Search for `schedule.power_pet_door_inside_schedule` or `schedule.power_pet_door_outside_schedule`
3. View the entity state and all attributes

#### Method 3: Exported JSON Files
Schedule data is automatically exported to JSON files for backup and inspection:
- **Location**: `{HA_CONFIG_DIR}/powerpetdoor/exports/`
- **Filename format**: `schedule_export_YYYYMMDD_HHMMSS.json`
- **Contents**: Full schedule data including timestamps, device ID, and all schedule entries
- **Retention**: The 5 most recent export files are kept automatically

#### Method 4: Entity Attributes
Schedule entities include readable attributes:
- `schedule_entries`: Array of formatted schedule strings showing days and time windows
- `schedule_count`: Total number of active schedule entries

### Editing Schedules

**Note**: The built-in Home Assistant Schedule UI editor is not available for custom integration schedule entities due to a limitation in Home Assistant's Schedule component. However, you can edit schedules using the methods below.

#### Method 1: Using the Service

Use the `powerpetdoor.update_schedule` service to programmatically update schedules:

**Service**: `powerpetdoor.update_schedule`

**Parameters**:
- `entity_id` (required): The schedule entity to update (e.g., `schedule.power_pet_door_inside_schedule`)
- `schedule` (required): Schedule configuration in Home Assistant format

**Schedule Format**:
```yaml
schedule:
  monday:
    - from: "06:00:00"
      to: "20:00:00"
  tuesday:
    - from: "06:00:00"
      to: "20:00:00"
  wednesday:
    - from: "06:00:00"
      to: "20:00:00"
  thursday:
    - from: "06:00:00"
      to: "20:00:00"
  friday:
    - from: "06:00:00"
      to: "20:00:00"
  saturday:
    - from: "08:00:00"
      to: "18:00:00"
  sunday:
    - from: "08:00:00"
      to: "18:00:00"
```

**Example Service Call** (via Developer Tools → Services):
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

#### Method 2: Using Automations

You can create automations that update schedules based on conditions:

```yaml
automation:
  - alias: "Update Pet Door Schedule for Weekdays"
    trigger:
      - platform: time
        at: "00:00:00"
    condition:
      condition: time
      weekday:
        - mon
        - tue
        - wed
        - thu
        - fri
    action:
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
          wednesday:
            - from: "06:00:00"
              to: "20:00:00"
          thursday:
            - from: "06:00:00"
              to: "20:00:00"
          friday:
            - from: "06:00:00"
              to: "20:00:00"
```

#### Method 3: Using the Device App

As a fallback, you can edit schedules using the official Power Pet Door mobile app. The integration will automatically fetch the updated schedule on the next refresh (default: every 5 minutes).

### Schedule Service Details

**Service Name**: `powerpetdoor.update_schedule`

**Description**: Updates a Power Pet Door schedule entity with new schedule configuration.

**Parameters**:
- `entity_id` (string, required): Target schedule entity ID
- `schedule` (dict, required): Schedule configuration with weekday keys and time window arrays

**Schedule Dictionary Format**:
- Keys: `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`
- Values: Array of time window objects with `from` and `to` time strings (HH:MM:SS format)

**Example**:
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
      - from: "12:00:00"
        to: "13:00:00"  # Multiple time windows per day are supported
```

**Notes**:
- Changes are immediately synced to the Power Pet Door device
- All existing schedules on the device are deleted and replaced with the new schedule
- The schedule is validated before being sent to the device
- Service calls are logged for debugging

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
```

### Schedule Calendar View Card

![Schedule Calendar Card](images/schedule-calendar-card.png)

This card displays a visual weekly calendar showing both Inside and Outside sensor schedules in a single grid view. Schedule times are color-coded (green for Inside, blue for Outside) and displayed for each day of the week.

**Prerequisites:**
- Install the [HTML Jinja2 Template card](https://github.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card) via HACS or manually
- Ensure your schedule entities are enabled and have schedule data configured

**Installation via HACS:**
1. Go to **HACS** → **Frontend**
2. Click the three-dot menu → **Custom repositories**
3. Add repository: `https://github.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card`
4. Set category to **Lovelace** and click **Add**
5. Find **Lovelace HTML Jinja2 Template card** and click **Download**
6. Restart Home Assistant

**Manual Installation:**
1. Download `html-template-card.js` from the [GitHub repository](https://github.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card)
2. Place the file in your Home Assistant `www` directory (create it if it doesn't exist)
3. Add the resource in Home Assistant: **Settings** → **Dashboards** → **Resources** → **Add Resource**
   - URL: `/local/html-template-card.js`
   - Resource type: **JavaScript Module**
4. Restart Home Assistant

**Card Configuration:**

Replace `schedule.dog_door_dog_door_inside_schedule` and `schedule.dog_door_dog_door_outside_schedule` with your actual schedule entity IDs. You can find these in **Developer Tools** → **States** by searching for "schedule".

```yaml
type: custom:html-template-card
title: Pet Door Schedules
ignore_line_breaks: true
always_update: true
entities:
  - schedule.dog_door_dog_door_inside_schedule
  - schedule.dog_door_dog_door_outside_schedule
content: |
  {% set inside_entity = states['schedule.dog_door_dog_door_inside_schedule'] %}
  {% set outside_entity = states['schedule.dog_door_dog_door_outside_schedule'] %}
  {% set day_abbrevs = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] %}
  
  <style>
    .schedule-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; margin: 12px 0; }
    .schedule-day-header { padding: 10px 8px; background: var(--primary-color); color: white; text-align: center; border-radius: 4px; font-weight: bold; font-size: 0.95em; }
    .schedule-day-cell { min-height: 80px; padding: 4px; background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 4px; }
    .schedule-time-block { padding: 8px 6px; margin: 4px 0; border-radius: 4px; text-align: center; font-size: 0.85em; font-weight: 500; color: white; }
    .schedule-time-inside { background: var(--success-color); }
    .schedule-time-outside { background: var(--info-color); }
    .schedule-empty { padding: 8px; text-align: center; color: var(--disabled-text-color); font-size: 0.85em; }
    .schedule-day-cell:has(.schedule-time-block) .schedule-empty { display: none; }
    .schedule-summary { margin-top: 16px; padding: 12px; background: var(--info-color); border-radius: 4px; font-size: 0.9em; }
    .schedule-legend { display: flex; gap: 16px; margin-bottom: 12px; font-size: 0.9em; }
    .legend-item { display: flex; align-items: center; gap: 6px; }
    .legend-color { width: 20px; height: 20px; border-radius: 4px; }
    .legend-inside { background: var(--success-color); }
    .legend-outside { background: var(--info-color); }
  </style>
  
  {% if (inside_entity and inside_entity.state != 'unavailable' and inside_entity.attributes) or (outside_entity and outside_entity.state != 'unavailable' and outside_entity.attributes) %}
    <div class="schedule-legend">
      <div class="legend-item">
        <div class="legend-color legend-inside"></div>
        <span>Inside Sensor</span>
      </div>
      <div class="legend-item">
        <div class="legend-color legend-outside"></div>
        <span>Outside Sensor</span>
      </div>
    </div>
    
    <div class="schedule-grid">
      {% for day in day_abbrevs %}<div class="schedule-day-header">{{ day }}</div>{% endfor %}
      {% for day_abbrev in day_abbrevs %}
        <div class="schedule-day-cell">
          {%- if inside_entity and inside_entity.attributes and inside_entity.attributes.get('schedule_entries') -%}
            {%- for entry in inside_entity.attributes.schedule_entries -%}
              {%- if day_abbrev in entry -%}
                {%- set parts = entry.split(': ') -%}
                {%- if parts|length >= 2 -%}
                  <div class="schedule-time-block schedule-time-inside">{{ parts[1] }}</div>
                {%- endif -%}
              {%- endif -%}
            {%- endfor -%}
          {%- endif -%}
          {%- if outside_entity and outside_entity.attributes and outside_entity.attributes.get('schedule_entries') -%}
            {%- for entry in outside_entity.attributes.schedule_entries -%}
              {%- if day_abbrev in entry -%}
                {%- set parts = entry.split(': ') -%}
                {%- if parts|length >= 2 -%}
                  <div class="schedule-time-block schedule-time-outside">{{ parts[1] }}</div>
                {%- endif -%}
              {%- endif -%}
            {%- endfor -%}
          {%- endif -%}
          <div class="schedule-empty">—</div>
        </div>
      {% endfor %}
    </div>
    
    <div class="schedule-summary">
      {% if inside_entity and inside_entity.attributes %}
        <strong>Inside:</strong> {{ inside_entity.attributes.get('schedule_count', 0) }} entries
        {% if inside_entity.attributes.get('last_change') %} (Updated: {{ inside_entity.attributes.last_change | as_datetime | as_local }}){% endif %}
      {% else %}
        <strong>Inside:</strong> Not available
      {% endif %}
      <br>
      {% if outside_entity and outside_entity.attributes %}
        <strong>Outside:</strong> {{ outside_entity.attributes.get('schedule_count', 0) }} entries
        {% if outside_entity.attributes.get('last_change') %} (Updated: {{ outside_entity.attributes.last_change | as_datetime | as_local }}){% endif %}
      {% else %}
        <strong>Outside:</strong> Not available
      {% endif %}
    </div>
  {% else %}
    <div style="padding: 20px; text-align: center; color: var(--error-color);">
      <p><strong>Schedule entities not available</strong></p>
    </div>
  {% endif %}
```

**Features:**
- **Weekly Calendar Grid**: Displays all 7 days of the week in a single row
- **Color-Coded Schedules**: Green blocks for Inside Sensor, blue blocks for Outside Sensor
- **Multiple Time Windows**: Supports multiple schedule entries per day
- **Auto-Hide Empty Days**: Days without schedules show a dash (—) only when no times are configured
- **Schedule Summary**: Shows total entries and last update time for both sensors
- **Legend**: Visual guide showing which color represents which sensor

**Customization:**
- Adjust colors by modifying the CSS variables (`--success-color` for inside, `--info-color` for outside)
- Change cell height by adjusting `min-height` in `.schedule-day-cell`
- Modify spacing by changing the `gap` value in `.schedule-grid`

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