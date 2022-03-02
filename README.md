# Power Pet Door by High Tech Pet

Custom component to allow control and monitoring of the Power Pet Door made by High Tech Pet

This addon was NOT made by anyone affiliated with High Tech Pet, don't bug them about it!

## Install

1. Ensure Home Assistant is updated to version 2021.4.0 or newer.
1. Use HACS, and add a [custom repository](https://github.com/corporategoth/ha-powerpetdoor)
1. Search HACS integrations for Power Pet Door and install it.
1. Once the integration is installed, restart your Home Assistant.
1. Edit your `configuration.yaml` file to add a powerpetdoor 'switch' (see configuration below)
1. Restart Home Assistant again to pick switch.

## Configuration

Your `configuration.yaml` should have a section like the following:

```
switch powerpetdoor:
  - platform: powerpetdoor
    host: 192.168.1.58
```

| Option | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| name | No | Power Pet Door | A pretty name for your Power Pet door entity |
| host | Yes |  | The host name or IP address of your Power Pet Door |
| port | No | 3000 | The port of your Power Pet Door |
| hold | No | true | Whether the default behavior of opening the door (ie. turning it 'on') will keep the door open or let it close by itself |
| timeout | No | 5.0 | Time out on attempting to connect to your Power Pet Door (seconds) |
| reconnect | No | 30.0 | How long to wait between retrying to connect to your Power Pet Door if disconnected (seconds) |
| keep_alive | No | 30.0 | How often will we send a PING keep alive message to the Power Pet Door (seconds) |
| refresh | No | 300.0 | How often we pull the configuration settings from the Power Pet Door (seconds) |

## Service calls

The Power Pet Door presents as a switch, which means it has a simple 'on' and 'off' state (on being opened, off being closed).
The standard homeassistant.turn_on, homeassistant.turn_off and homeassistant.toggle calls all work as expected also.

However, additional commands have been added to change the various behavior of the Power Pet Door

All service calls require an entity ID, so a sample call would look like:

```
service: powerpetdoor.open
entity_id: switch.power_pet_door
data:
    hold: false
```

### Door Commands

For actuating the door itself.

| Function | Arguments | Description |
| :--- | :--- | :--- |
| powerpetdoor.open | hold | Whether to hold the door open (ie. do not auto-close).  If not specified, uses the hold setting in configuration.yaml. |
| powerpetdoor.close | |  |
| powerpetdoor.toggle | hold | Whether to hold the door open (ie. do not auto-close).  If not specified, uses the hold setting in configuration.yaml. |

### Sensor Commands

For controlling the door sensors (ie. if the pet is detected inside or outside of the door for automatic opening)

| Function | Arguments | Description |
| :--- | :--- | :--- |
| powerpetdoor.enable_sensor  | sensor    | The sensor to enable (one of 'inside' or 'outside') |
| powerpetdoor.disable_sensor | sensor    | The sensor to disable (one of 'inside' or 'outside') |
| powerpetdoor.toggle_sensor  | sensor    | The sensor to toggle (one of 'inside' or 'outside') |

### Automatic (scheduled) Mode Commands

For controlling automatic (scheduled) mode - which automatically enables the indoor and outdoor sensors on a schedule.
Adjusting the schedule for these sensors must be done via. the app, and cannot be changed in Home Assistant.

| Function | Arguments | Description |
| :--- | :--- | :--- |
| powerpetdoor.enable_auto  | | |
| powerpetdoor.disable_auto | | |
| powerpetdoor.toggle_auto  | | |

### Power Commands

For controlling the power on/off state of the door.  Note that even when 'powered off', WiFi is still enabled on the door
(otherwise you would be unable to power it back on remotely).

| Function | Arguments | Description |
| :--- | :--- | :--- |
| powerpetdoor.power_on     | | |
| powerpetdoor.power_off    | | |
| powerpetdoor.power_toggle | | |

## Credits

Big thanks to the authors of the [Envisalink component](https://home-assistant.io/integrations/envisalink), which I based a lot of the async networking code off of.

