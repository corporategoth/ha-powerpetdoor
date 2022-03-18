# Power Pet Door by High Tech Pet

Custom component to allow control and monitoring of the Power Pet Door made by High Tech Pet

This addon was NOT made by anyone affiliated with High Tech Pet, don't bug them about it!

## Install

1. Ensure Home Assistant is updated to version 2021.4.0 or newer.
1. Use HACS, and add a [custom repository](https://github.com/corporategoth/ha-powerpetdoor)
1. Search HACS integrations for Power Pet Door and install it.
1. Once the integration is installed, restart your Home Assistant.
1. Under Integrations, add Power Pet Door, and configure it appropriately.

## Configuration

You can go to the Integrations page and add a Power Pet Door integration.

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
| update | No |  | How often we update the current door position (seconds) |

## Service calls

The door entity (which would be something like switch.power_pet_door) responds to standard turn_on, and turn_off and toggle
service calls.  However, in order to support the hold option above (ie. override the default), open and close service calls
have been added that support the extra hold option.

| Function | Arguments | Description |
| :--- | :--- | :--- |
| powerpetdoor.open | hold | Whether to hold the door open (ie. do not auto-close).  If not specified, uses the hold setting in configuration.yaml. |
| powerpetdoor.close | | |
| powerpetdoor.toggle | hold | Whether to hold the door open (ie. do not auto-close).  If not specified, uses the hold setting in configuration.yaml. |

## Credits

Big thanks to the authors of the [Envisalink component](https://home-assistant.io/integrations/envisalink), which I based a lot of the async networking code off of.

