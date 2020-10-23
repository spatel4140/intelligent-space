import os
import sys
#sys.path.append('/home/pi/.local/lib/python3.5/site-packages')
from src import config
from Adafruit_IO import MQTTClient
from RPi import GPIO
import time
from subprocess import Popen, PIPE
from datetime import datetime, timedelta
import re
import Adafruit_DHT                                             # git+https://github.com/adafruit/Adafruit_Python_DHT.git#egg=Adafruit_Python_DHT
import logging
from src.db import DB
from dateutil import tz
from logging.handlers import TimedRotatingFileHandler





class Space:
    __REFRESH_RATE                          = 120               # seconds
    __MAX_CPU_TEMP                          = 150               # fahrenheit (65 celcius)
    __TV_SLEEP_TIMER_DUR                    = 30                # minutes

    __DT_FMT                                = "%a, %b %d %Y %I:%M%p %Z"
    __LOCAL_TZ                              = tz.tzlocal()

    __DEBUG                                 = True


    def __init__(self, config): 
        self.config                         = config


        self.__cur_lights_relay_state       = 0                 # start on
        self.__cur_fan_relay_state          = 1                 # start off
        self.__cur_cpu_fan_state            = 0                 # start off

        self.__prev_lights_switch_state     = -1
        self.__prev_fan_switch_state        = -1
        self.__prev_door_state              = -1

        self.__prev_cpu_temp                = -1
        self.__prev_humidity                = -1
        self.__prev_room_temp               = -1

        self.__cur_time                     = datetime.now(self.__LOCAL_TZ)
        self.__prev_time                    = datetime.now(self.__LOCAL_TZ) - timedelta(seconds=self.__REFRESH_RATE)
        self.__prev_date                    = (self.__cur_time - timedelta(days=1)).date()

        self.__is_tv_sleep_timer            = 0                 # 0 (off), 1 (30 minutes) or 2 (60 minutes)
        self.__tv_sleep_time                = None



        # create rotating log file
        if not os.path.exists("logs"):
            os.makedirs("logs")

        # rotate every saturday
        logging_handler = TimedRotatingFileHandler("logs/debug.log", when="w5", interval=1, backupCount=4)
        logging_handler.suffix = "%Y-%m-%dT%H:%M:%S"
        logging_formatter = logging.Formatter("%(asctime)s.%(msecs)03d:%(levelname)-8s:%(message)s", datefmt=self.__DT_FMT)
        logging_handler.setFormatter(logging_formatter)
        self.__logger = logging.getLogger()
        self.__logger.addHandler(logging_handler)
        self.__logger.setLevel(logging.DEBUG)

        # halt logging from Adafruit_IO lib
        adafruit_log = logging.getLogger("Adafruit_IO")
        adafruit_log.propagate = False


        # create db to hold feed history
        self.__db                        = DB("logs/feeds.db", self.config.feeds.values())


        # populate prev_* variables if history exists in the db
        lights_state_feed = self.config.feeds["lights_state"]
        prev_lights_state = self.__db.select_prev_state(lights_state_feed)
        if prev_lights_state is not None:
            self.__cur_lights_relay_state = int(not prev_lights_state)
            self.__std_out("previous {}: {}".format(lights_state_feed, "on" if prev_lights_state else "off"))
        fan_state_feed = self.config.feeds["fan_state"]
        prev_fan_state = self.__db.select_prev_state(fan_state_feed)
        if prev_fan_state is not None:
            self.__cur_fan_relay_state = int(not prev_fan_state)
            self.__std_out("previous {}: {}".format(fan_state_feed, "on" if prev_fan_state else "off"))
        door_contact_feed = self.config.feeds["door_state"]
        prev_door_state = self.__db.select_prev_state(door_contact_feed)
        if prev_door_state is not None:
            self.__prev_door_state = prev_door_state
            self.__std_out("previous {}: {}".format(door_contact_feed, "closed" if prev_door_state else "open"))


        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup(self.config.pins['lights_switch'], GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.config.pins['lights_relay'], GPIO.OUT)
        GPIO.setup(self.config.pins['fan_switch'], GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.config.pins['fan_relay'], GPIO.OUT)
        GPIO.setup(self.config.pins['door_contact'], GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.config.pins['motor_in_1'], GPIO.OUT)
        GPIO.setup(self.config.pins['motor_in_2'], GPIO.OUT)
        GPIO.setup(self.config.pins['motor_enable'], GPIO.OUT)
        GPIO.setup(self.config.pins['cpu_fan_enable'], GPIO.OUT)


        # connect to adafruit io
        self.__client = MQTTClient(self.config.credentials['username'], self.config.credentials['key'])
        self.__client.on_connect = self.__on_connect
        self.__client.on_disconnect = self.__on_disconnect
        self.__client.on_message = self.__on_message
        self.__connect()

        # client was previously not connected during call to handle_state_change(), current state may not have been published
        self.__client.publish(lights_state_feed, self.__cur_lights_relay_state)
        self.__client.publish(fan_state_feed, self.__cur_fan_relay_state)
        self.__client.publish(door_contact_feed, self.__prev_door_state)
        self.__client.publish(self.config.feeds['tv_sleep_timer'], 0)


    def __std_out(self, output):
        if self.__DEBUG:
            print("{}: {}".format(self.__cur_time.strftime(self.__DT_FMT), output))


    def __change_lights_state(self, lights_state):
        self.__cur_lights_relay_state = lights_state
        GPIO.output(self.config.pins['lights_relay'], int(not lights_state))

        lights_state_feed = self.config.feeds["lights_state"]
        self.__std_out("{} -> {}".format(lights_state_feed, "on" if lights_state else "off"))
        self.__db.insert_cur_state(lights_state_feed, lights_state, self.__cur_time)
        self.__client.publish(lights_state_feed, lights_state)
    def __change_fan_state(self, fan_state):
        self.__cur_fan_relay_state = fan_state
        GPIO.output(self.config.pins['fan_relay'], int(not fan_state))

        fan_state_feed = self.config.feeds["fan_state"]
        self.__std_out("{} -> {}".format(fan_state_feed, "on" if fan_state else "off"))
        self.__db.insert_cur_state(fan_state_feed, fan_state, self.__cur_time)
        self.__client.publish(fan_state_feed, fan_state)
    def __change_lock_state(self, lock_state):
        GPIO.output(self.config.pins['motor_in_1'], lock_state)
        GPIO.output(self.config.pins['motor_in_2'], int(not lock_state))
        GPIO.output(self.config.pins['motor_enable'], GPIO.HIGH)
        time.sleep(.2)
        GPIO.output(self.config.pins['motor_enable'], GPIO.LOW)

        door_lock_feed = self.config.feeds["door_lock"]
        self.__std_out("{} -> {}".format(door_lock_feed, "locked" if lock_state else "unlocked"))
        self.__db.insert_cur_state(door_lock_feed, lock_state, self.__cur_time)
    def __change_cpu_fan_state(self, cpu_fan_state):
        self.__cur_cpu_fan_state = cpu_fan_state
        GPIO.output(self.config.pins['cpu_fan_enable'], cpu_fan_state)

        cpu_fan_state_feed = self.config.feeds["cpu_fan_state"]
        self.__std_out("{} -> {}".format(cpu_fan_state_feed, "on" if cpu_fan_state else "off"))
        self.__db.insert_cur_state(cpu_fan_state_feed, cpu_fan_state, self.__cur_time)

    def __handle_lights_switch_state_change(self):
        cur_lights_switch_state = GPIO.input(self.config.pins['lights_switch'])
        if cur_lights_switch_state != self.__prev_lights_switch_state:
            lights_switch_feed = self.config.feeds["lights_switch"]
            self.__std_out("{} -> {}".format(lights_switch_feed, cur_lights_switch_state))

            self.__prev_lights_switch_state = cur_lights_switch_state
            self.__change_lights_state(int(not self.__cur_lights_relay_state))

            self.__db.insert_cur_state(lights_switch_feed, cur_lights_switch_state, self.__cur_time)
    def __handle_fan_switch_state_change(self):
        cur_fan_switch_state = GPIO.input(self.config.pins['fan_switch'])
        if cur_fan_switch_state != self.__prev_fan_switch_state:
            fan_switch_feed = self.config.feeds["fan_switch"]
            self.__std_out("{} -> {}".format(fan_switch_feed, cur_fan_switch_state))

            self.__prev_fan_switch_state = cur_fan_switch_state
            self.__change_fan_state(int(not self.__cur_fan_relay_state))

            self.__db.insert_cur_state(fan_switch_feed, cur_fan_switch_state, self.__cur_time)
    def __handle_door_state_change(self):
        cur_door_state = int(not GPIO.input(self.config.pins['door_contact']))
        if cur_door_state != self.__prev_door_state:
            self.__prev_door_state = cur_door_state

            door_state_feed = self.config.feeds["door_state"]
            self.__std_out("{}: {}".format(door_state_feed, "closed" if cur_door_state else "open"))
            self.__db.insert_cur_state(door_state_feed, cur_door_state, self.__cur_time)
            self.__client.publish(door_state_feed, cur_door_state)

            if cur_door_state == 1: # if just closed, lock door
                self.__change_lock_state(1)
    def __handle_cpu_temp_change(self):
        # run parallel thread
        output, error = Popen(["vcgencmd", "measure_temp"], stdout=PIPE).communicate()
        cpu_temp = float(re.match("temp=(\d+.\d+)'C", output.decode()).group(1)) *9/5.+32
        
        if cpu_temp != self.__prev_cpu_temp:
            self.__prev_cpu_temp = cpu_temp

            cpu_temp_feed = self.config.feeds["cpu_temp"]
            self.__std_out("{}: {} degrees fahrenheit".format(cpu_temp_feed, cpu_temp))
            self.__db.insert_cur_state(cpu_temp_feed, cpu_temp, self.__cur_time)
            self.__client.publish(cpu_temp_feed, cpu_temp)
    
            if cpu_temp > self.__MAX_CPU_TEMP:
                if self.__cur_cpu_fan_state == 0:
                    self.__change_cpu_fan_state(1)
            elif self.__cur_cpu_fan_state == 1:
                self.__change_cpu_fan_state(0)
    def __handle_dht_change(self):
        # run parallel thread
        humidity, room_temp = Adafruit_DHT.read(Adafruit_DHT.DHT22, self.config.pins['dht_sensor'])
        if humidity != self.__prev_humidity:
            self.__prev_humidity = humidity

            humidity_feed = self.config.feeds["humidity"]
            self.__std_out("{}: {}".format(humidity_feed, humidity))
            self.__db.insert_cur_state(humidity_feed, humidity, self.__cur_time)
            if humidity:
                self.__client.publish(humidity_feed, humidity)

        if room_temp:
            room_temp = room_temp *9/5.+32
        if room_temp != self.__prev_room_temp:
            self.__prev_room_temp = room_temp

            room_temp_feed = self.config.feeds["room_temp"]
            self.__std_out("{}: {}".format(room_temp_feed, room_temp))
            self.__db.insert_cur_state(room_temp_feed, room_temp, self.__cur_time)
            #if room_temp:
            #    self.__client.publish(room_temp_feed, room_temp)
    def __handle_tv_sleep_timer(self):
        if self.__is_tv_sleep_timer > 0:
            minutes_remaining = (self.__tv_sleep_time-self.__cur_time).total_seconds() // 60 + 1
            if minutes_remaining <= 0:
                # reset brightness 
                Popen(['irsend', 'SEND_ONCE', 'tv', 'power'])
                self.__is_tv_sleep_timer = 0
                minutes_remaining = 0

            tv_sleep_timer_feed = self.config.feeds["tv_sleep_timer"]
            self.__std_out("{}: {} minutes remaining".format(tv_sleep_timer_feed, minutes_remaining))
            self.__db.insert_cur_state(tv_sleep_timer_feed, minutes_remaining, self.__cur_time)
            self.__client.publish(tv_sleep_timer_feed, minutes_remaining)

    def __handle_state_change(self):
        self.__cur_time = datetime.now(self.__LOCAL_TZ)

        self.__handle_lights_switch_state_change()
        self.__handle_fan_switch_state_change() 
        self.__handle_door_state_change()

        if (self.__cur_time-self.__prev_time).total_seconds() > self.__REFRESH_RATE:
            self.__prev_time = self.__cur_time#.replace(second=0)

            self.__handle_cpu_temp_change()
            self.__handle_dht_change()

            self.__handle_tv_sleep_timer()


    def __on_connect(self, client):
        msg = 'Connected to Adafruit IO!'
        self.__std_out(msg)
        self.__logger.info(msg)

        self.__client.subscribe(self.config.feeds['lights_switch'])
        self.__client.subscribe(self.config.feeds['fan_switch'])
        self.__client.subscribe(self.config.feeds['door_lock'])
        self.__client.subscribe(self.config.feeds['tv_remote'])
    def __on_disconnect(self, client):
        msg = 'Disconnected from Adafruit IO!'
        self.__std_out(msg)
        self.__logger.info(msg)

        self.__connect()
    def __on_message(self, client, feed_id, payload):
        if feed_id == self.config.feeds['lights_switch']:
            if payload == "ON":
                if self.__cur_lights_relay_state != 1:
                    self.__change_lights_state(1)
            else: 
                if self.__cur_lights_relay_state != 0:
                    self.__change_lights_state(0)

        elif feed_id == self.config.feeds['fan_switch']:
            if payload == "ON":
                if self.__cur_fan_relay_state != 1:
                    self.__change_fan_state(1)
            else:
                if self.__cur_fan_relay_state != 0:
                    self.__change_fan_state(0)

        elif feed_id == self.config.feeds['door_lock']:
            if payload == "UNLOCK":
                self.__change_lock_state(0)
            else:
                self.__change_lock_state(1)

        elif feed_id == self.config.feeds['tv_remote']:
            self.__std_out("{} <- {}".format(feed_id, payload))
            self.__db.insert_cur_state(feed_id, payload, self.__cur_time)

            if payload == "0": # volume down
                Popen(['irsend', 'SEND_ONCE', 'tv', 'volume_down'])
            elif payload == "1": # play/pause 
                Popen(['irsend', 'SEND_ONCE', 'tv', 'power'])
            elif payload == "2": # volume up
                Popen(['irsend', 'SEND_ONCE', 'tv', 'volume_up'])
            elif payload == "4": # setup
                Popen(['irsend', 'SEND_ONCE', 'tv', 'source'])
            elif payload == "5": # arrow up
                Popen(['irsend', 'SEND_ONCE', 'tv', 'arrow_up'])
            elif payload == "6": # stop/mode
                Popen(['irsend', 'SEND_ONCE', 'tv', 'mute'])
            elif payload == "8": # arrow left
                Popen(['irsend', 'SEND_ONCE', 'tv', 'arrow_left'])
            elif payload == "9": # enter/save
                Popen(['irsend', 'SEND_ONCE', 'tv', 'ok'])
            elif payload == "10": # arrow right
                Popen(['irsend', 'SEND_ONCE', 'tv', 'arrow_right'])
            elif payload == "12": # 0
                Popen(['irsend', 'SEND_ONCE', 'tv', '0'])
            elif payload == "13": # arrow down
                Popen(['irsend', 'SEND_ONCE', 'tv', 'arrow_down'])
            elif payload == "14": # back
                #Popen(['irsend', 'SEND_ONCE', 'tv', 'back'])
                if self.__is_tv_sleep_timer == 0:
                    self.__is_tv_sleep_timer = 1
                    # dim brightness
                    self.__tv_sleep_time = self.__cur_time + timedelta(minutes=self.__TV_SLEEP_TIMER_DUR)
                    minutes_remaining = self.__TV_SLEEP_TIMER_DUR
                elif self.__is_tv_sleep_timer == 1:
                    self.__is_tv_sleep_timer = 2
                    self.__tv_sleep_time += timedelta(minutes=self.__TV_SLEEP_TIMER_DUR)
                    minutes_remaining = (self.__tv_sleep_time-self.__cur_time).total_seconds() // 60 + 1
                else:
                    self.__is_tv_sleep_timer = 0
                    # reset brightness
                    minutes_remaining = 0

                tv_sleep_timer_feed = self.config.feeds['tv_sleep_timer']
                self.__std_out("{}: {} minutes remaining".format(tv_sleep_timer_feed, minutes_remaining))
                self.__db.insert_cur_state(tv_sleep_timer_feed, minutes_remaining, self.__cur_time)
                self.__client.publish(tv_sleep_timer_feed, minutes_remaining)
            elif payload == "16": # 1
                Popen(['irsend', 'SEND_ONCE', 'tv', '1'])
            elif payload == "17": # 2
                Popen(['irsend', 'SEND_ONCE', 'tv', '2'])
            elif payload == "18": # 3
                Popen(['irsend', 'SEND_ONCE', 'tv', '3'])
            elif payload == "20": # 4
                Popen(['irsend', 'SEND_ONCE', 'tv', '4'])
            elif payload == "21": # 5
                Popen(['irsend', 'SEND_ONCE', 'tv', '5'])
            elif payload == "22": # 6
                Popen(['irsend', 'SEND_ONCE', 'tv', '6'])
            elif payload == "24": # 7
                Popen(['irsend', 'SEND_ONCE', 'tv', '7'])
            elif payload == "25": # 8
                Popen(['irsend', 'SEND_ONCE', 'tv', '8'])
            elif payload == "26": # 9
                Popen(['irsend', 'SEND_ONCE', 'tv', '9'])

    def __connect(self):
        msg = "Connecting to Adafruit IO.."
        self.__std_out(msg)
        self.__logger.info(msg)

        while True:
            self.__handle_state_change() # handle state changes while trying to connect
            try:
                self.__client.connect()
                return
            except:
                pass

            time.sleep(.2)


    def loop_forever(self):
        while True:
            try:
                #self.__client.loop_background()

                # for some reason, calling client.is_connected() fails for the first few seconds
                init_time = self.__cur_time + timedelta(seconds=2)
                while self.__cur_time < init_time:
                    self.__handle_state_change()
                    self.__client.loop() # blocks for 1 second


                # run forever 
                while True:
                    self.__handle_state_change()

                    if self.__client.is_connected():
                        self.__client.loop()
                    else:
                        msg = "No longer connected to Adafruit IO!"
                        self.__std_out(msg)
                        self.__logger.warn(msg)

                        self.__connect()
                        break

                    # delete old db records
                    if self.__cur_time.date() != self.__prev_date:
                        month_ago_time = self.__cur_time - timedelta(days=30)
                        self.__db.delete_old_state_records(month_ago_time)
                        self.__prev_date = self.__cur_time.date()

            except: # will not be caught during reboot
                if self.__cur_cpu_fan_state == 1:
                    self.__change_cpu_fan_state(0)

                self.__logger.exception("")
                raise




if __name__ == "__main__":
    # set working dir to script dir
    dir_run_from = os.getcwd()
    script_dir = os.path.dirname(sys.argv[0])
    if script_dir and script_dir != dir_run_from:
        os.chdir(script_dir)

    space = Space(config)
    space.loop_forever()

