# *****************************************************************************
# * | File        :   new4in26part.py
# * | Author      :   Waveshare team + Zerowriter modifications
# * | Function    :   Electronic paper driver for 4.26" with partial refresh
# * | Info        :
# *----------------
# * | This version:   V1.0
# * | Date        :   2024-12-21
# # | Info        :   Adapted for zerowriter from 4in2 partial refresh driver
# -----------------------------------------------------------------------------
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# Zerowriter Project disclaimer:
#
# This driver adapts the 4.2" fast partial refresh LUT for the 4.26" display.
# Use at your own risk - settings push display outside recommended specs.
#

import logging
import epdconfig
from PIL import Image
import time

# Display resolution for 4.26"
EPD_WIDTH  = 800
EPD_HEIGHT = 480

GRAY1 = 0xff  # white
GRAY2 = 0xC0
GRAY3 = 0x80  # gray
GRAY4 = 0x00  # Blackest

logger = logging.getLogger(__name__)

class EPD:
    def __init__(self):
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin = epdconfig.DC_PIN
        self.busy_pin = epdconfig.BUSY_PIN
        self.cs_pin = epdconfig.CS_PIN
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT
        self.GRAY1 = GRAY1
        self.GRAY2 = GRAY2
        self.GRAY3 = GRAY3
        self.GRAY4 = GRAY4

    # Fast partial refresh LUT (from 4.2" driver)
    lut_vcom0 = [
        0x00, 0x0E, 0x00, 0x00, 0x00, 0x01,        
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,        
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,        
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,        
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,        
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,        
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    lut_ww = [
        0xA0, 0x0E, 0x00, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    lut_bw = [
        0xA0, 0x0E, 0x00, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    lut_wb = [
        0x50, 0x0E, 0x00, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    lut_bb = [
        0x50, 0x0E, 0x00, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00 
    ]
    
    # Slow LUT for full refresh (clears artifacts)
    slow_lut_vcom0 = [
        0x00, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x00, 0x0F, 0x0F, 0x00, 0x00, 0x01,
        0x00, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00,
    ]
    
    slow_lut_ww = [
        0x50, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x90, 0x0F, 0x0F, 0x00, 0x00, 0x01,
        0xA0, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    slow_lut_bw = [
        0x50, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x90, 0x0F, 0x0F, 0x00, 0x00, 0x01,
        0xA0, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    slow_lut_wb = [
        0xA0, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x90, 0x0F, 0x0F, 0x00, 0x00, 0x01,
        0x50, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    slow_lut_bb = [
        0x20, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x90, 0x0F, 0x0F, 0x00, 0x00, 0x01,
        0x10, 0x08, 0x08, 0x00, 0x00, 0x02,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]

    # Hardware reset
    def reset(self):
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20) 
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(2)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)

    def send_command(self, command):
        epdconfig.digital_write(self.dc_pin, 0)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([command])
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([data])
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data2(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte2(data)
        epdconfig.digital_write(self.cs_pin, 1)

    def ReadBusy(self):
        logger.debug("e-Paper busy")
        busy = epdconfig.digital_read(self.busy_pin)
        while(busy == 1):
            busy = epdconfig.digital_read(self.busy_pin)
            epdconfig.delay_ms(20)
        epdconfig.delay_ms(20)
        logger.debug("e-Paper busy release")

    def set_lut(self):
        self.send_command(0x20)  # vcom
        self.send_data2(self.lut_vcom0)
        self.send_command(0x21)  # ww
        self.send_data2(self.lut_ww)
        self.send_command(0x22)  # bw
        self.send_data2(self.lut_bw)
        self.send_command(0x23)  # wb
        self.send_data2(self.lut_bb)
        self.send_command(0x24)  # bb
        self.send_data2(self.lut_wb)

    def set_slow_lut(self):
        self.send_command(0x20)  # vcom
        self.send_data2(self.slow_lut_vcom0)
        self.send_command(0x21)  # ww
        self.send_data2(self.slow_lut_ww)
        self.send_command(0x22)  # bw
        self.send_data2(self.slow_lut_bw)
        self.send_command(0x23)  # wb
        self.send_data2(self.slow_lut_bb)
        self.send_command(0x24)  # bb
        self.send_data2(self.slow_lut_wb)

    def init(self):
        if epdconfig.module_init() != 0:
            return -1
        
        self.reset()
        self.ReadBusy()

        self.send_command(0x12) # SWRESET
        self.ReadBusy()

        self.send_command(0x18) # use internal temperature sensor
        self.send_data(0x80)

        self.send_command(0x0C) # set soft start
        self.send_data(0xAE)
        self.send_data(0xC7)
        self.send_data(0xC3)
        self.send_data(0xC0)
        self.send_data(0x80)

        self.send_command(0x01) # drive output control
        self.send_data((self.height-1) % 256)
        self.send_data((self.height-1) // 256)
        self.send_data(0x02)

        self.send_command(0x3C) # Border setting
        self.send_data(0x01)

        self.send_command(0x11) # data entry mode
        self.send_data(0x01)

        # Set window
        self.send_command(0x44) # SET_RAM_X_ADDRESS_START_END_POSITION
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_data((self.width-1) & 0xFF)
        self.send_data(((self.width-1) >> 8) & 0x03)
        
        self.send_command(0x45) # SET_RAM_Y_ADDRESS_START_END_POSITION
        self.send_data((self.height-1) & 0xFF)
        self.send_data((self.height-1) >> 8)
        self.send_data(0x00)
        self.send_data(0x00)

        # Set cursor
        self.send_command(0x4E) # SET_RAM_X_ADDRESS_COUNTER
        self.send_data(0x00)
        self.send_data(0x00)
        
        self.send_command(0x4F) # SET_RAM_Y_ADDRESS_COUNTER
        self.send_data(0x00)
        self.send_data(0x00)
        
        self.ReadBusy()
        
        # Use slow LUT for full refresh (prevents artifacts)
        self.set_slow_lut()
        
        return 0

    def init_Partial(self):
        if epdconfig.module_init() != 0:
            return -1
        
        self.reset()
        self.ReadBusy()

        self.send_command(0x12) # SWRESET
        self.ReadBusy()

        self.send_command(0x18) # use internal temperature sensor
        self.send_data(0x80)

        self.send_command(0x0C) # set soft start
        self.send_data(0xAE)
        self.send_data(0xC7)
        self.send_data(0xC3)
        self.send_data(0xC0)
        self.send_data(0x80)

        self.send_command(0x01) # drive output control
        self.send_data((self.height-1) % 256)
        self.send_data((self.height-1) // 256)
        self.send_data(0x02)

        self.send_command(0x3C) # Border setting
        self.send_data(0x01)

        self.send_command(0x11) # data entry mode
        self.send_data(0x01)

        # Set window
        self.send_command(0x44) # SET_RAM_X_ADDRESS_START_END_POSITION
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_data((self.width-1) & 0xFF)
        self.send_data(((self.width-1) >> 8) & 0x03)
        
        self.send_command(0x45) # SET_RAM_Y_ADDRESS_START_END_POSITION
        self.send_data((self.height-1) & 0xFF)
        self.send_data((self.height-1) >> 8)
        self.send_data(0x00)
        self.send_data(0x00)

        # Set cursor
        self.send_command(0x4E) # SET_RAM_X_ADDRESS_COUNTER
        self.send_data(0x00)
        self.send_data(0x00)
        
        self.send_command(0x4F) # SET_RAM_Y_ADDRESS_COUNTER
        self.send_data(0x00)
        self.send_data(0x00)
        
        self.ReadBusy()
        
        # Use fast LUT for partial refresh
        self.set_lut()
        
        return 0

    def getbuffer(self, image):
        buf = [0xFF] * (int(self.width / 8) * self.height)
        image_monocolor = image.convert('1')
        imwidth, imheight = image_monocolor.size
        pixels = image_monocolor.load()
        
        if imwidth == self.width and imheight == self.height:
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0:
                        buf[int((x + y * self.width) / 8)] &= ~(0x80 >> (x % 8))
        elif imwidth == self.height and imheight == self.width:
            for y in range(imheight):
                for x in range(imwidth):
                    newx = y
                    newy = self.height - x - 1
                    if pixels[x, y] == 0:
                        buf[int((newx + newy * self.width) / 8)] &= ~(0x80 >> (y % 8))
        
        return buf

    def display(self, image):
        if self.width % 8 == 0:
            linewidth = int(self.width / 8)
        else:
            linewidth = int(self.width / 8) + 1

        # Don't send old data (0x10 command) - skip it for faster partial refresh
        self.send_command(0x24)  # Write new data
        self.send_data2(image)

        self.send_command(0x22) # Display Update Control
        self.send_data(0xC7)    # Use 0xC7 for partial, 0xF7 for full
        self.send_command(0x20) # Activate Display Update Sequence
        
        # Don't wait for busy - this speeds things up significantly
        self.ReadBusy()

    def Clear(self):
        if self.width % 8 == 0:
            linewidth = int(self.width / 8)
        else:
            linewidth = int(self.width / 8) + 1

        self.send_command(0x24)
        self.send_data2([0xFF] * int(self.height * linewidth))

        self.send_command(0x26)
        self.send_data2([0xFF] * int(self.height * linewidth))

        self.send_command(0x22) # Display Update Control
        self.send_data(0xF7)
        self.send_command(0x20) # Activate Display Update Sequence
        
        self.ReadBusy()

    def sleep(self):
        self.send_command(0x10) # DEEP_SLEEP
        self.send_data(0x01)
        
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()

### END OF FILE ###
