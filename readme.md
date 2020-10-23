
# Intelligent Space
Adding smart home capabilities


## Hardware Requirements
* [Raspberry Pi](https://www.adafruit.com/product/3055)
* [Relays](https://www.adafruit.com/product/3191)
* [Magnetic contact sensor](https://www.adafruit.com/product/375)
* [DC motor](https://www.radioshack.com/products/radioshack-6vdc-micro-super-high-speed-motor)
* [H-bridge](https://www.adafruit.com/product/807)
* [IR sensor](https://www.adafruit.com/product/157)
* [IR LED](https://www.adafruit.com/product/387)
* [CPU fan](https://www.adafruit.com/product/3368)
* [DHT sensor](https://www.adafruit.com/product/385)


## Getting Started
### Setup Raspberry Pi
1. Wire hardware
2. Add pins to **IntelligentSpace/src/config.py**
	```
	pins = dict(
		lights_switch   = -1,
		lights_relay    = -1,
		fan_switch      = -1,
		fan_relay       = -1,
		door_contact    = -1,
		motor_in_1      = -1,
		motor_in_2      = -1,
		motor_enable    = -1,
		cpu_fan_enable  = -1,
		dht_sensor      = -1,
	)
	```
3. Install requirements `sudo pip install -r IntelligentSpace/requirements.txt`
4. Add following line to **/etc/rc.local** to run in the background on boot: `(screen -dmS space bash -c 'python3 /home/pi/intelligent-space/IntelligentSpace/IntelligentSpace.py; exec sh')&`. Make sure you have Screen installed: `sudo apt-get install screen`
### Wire Door Lock
1. 3D print **Doorknob motor housing - Part 1.stl**
2. Secure DC motor in casing
3. Disassemble closet doorknob (side with no locking/unlocking mechanism) and place inside
4. Attach ordinary bedroom doorknob to the otherside
### Program TV remote
1. Install LIRC 
	`sudo apt-get install lirc`
2. Add the following lines in **/etc/modules** (where 18 is your IR sensor and 17 is your IR LED)
	```
	lirc_dev
	lirc_rpi gpio_in_pin=18 gpio_out_pin=17
	```
3. Add the following lines in **/etc/lirc/hardware.conf**
	```
	LIRCD_ARGS="--uinput --listen"
	LOAD_MODULES=true
	DRIVER="default"
	DEVICE="/dev/lirc0"
	MODULES="lirc_rpi"
	```
4. Change the following line in **/boot/config.txt** (where 18 is your IR sensor and 17 is your IR LED)
	`dtoverlay=lirc-rpi, gpio_in_pin=18, gpio_out_pin=17`
5. Change the following lines in **/etc/lirc/lirc_options.conf**
	```
	driver    = default
	device    = /dev/lirc0"
	```
6. Reboot
7. Stop the LIRC daemon before configuring remote
	`sudo /etc/init.d/lirc stop`
8. If you want to see IR signal timings
	`mode2 -d /dev/lirc0`
9. Start recording IR signals
	`irrecord -n -d /dev/lirc0`
10. Record the following namespace:
	* `power`
	* `volume_up`
	* `volume_down`
	* `mute`
	* `source`
	* `arrow_up`
	* `arrow_down`
	* `arrow_left`
	* `arrow_right`
	* `ok`
	* `back`
	* `0`
	* `1`
	* `2`
	* `3`
	* `4`
	* `5`
	* `6`
	* `7`
	* `8`
	* `9`
11. Replace the system LIRC file with yours
	`sudo cp lircd.conf /etc/lirc/lircd.conf`
12. Start LIRC service
	`sudo /etc/init.d/lirc start`
13. If you want to monitor assigned controls being pressed
	`irw`
### Connect Adafruit IO 
1. Generate access key
2. Add credentials to **IntelligentSpace/src/config.py**
	```
	credentials = dict(
		username		= '',
		key				= '',
	)
	```
3. Setup dashboard widgets
4. Add feeds to **IntelligentSpace/src/config.py**
	```
	feeds = dict(
		lights_switch   = '',
		lights_state    = '',
		fan_switch      = '',
		fan_state       = '',
		door_lock       = '',
		door_state      = '',
		tv_remote       = '',
		sleep_timer     = '',
		cpu_temp        = '',
		room_temp       = '',
	)
	```
### Add Google Assistant
1. Create IFTTT account
2. Connect Google account
3. Connect Adafruit IO account
4. Create applets
	* `turn on the lights`
	* `turn on the fan`
	* `lock the door`
	* `turn on the tv`

