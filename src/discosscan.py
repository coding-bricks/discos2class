#
#
#    Copyright (C) 2016  Marco Bartolini, bartolini@ira.inaf.it
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from ctypes import LibraryLoader
import os
import logging
logger = logging.getLogger(__name__)
from datetime import datetime
import sys
import glob
import numpy as np 

from astropy.io import fits
from astropy import units as u
from astropy.time import Time
from astropy.constants import c as C

import pyclassfiller
from pyclassfiller import code

from .scancycle import ScanCycle
from .progress import Progress

#SUMMARY = "summary.fits"

STOKES = "stokes"
CLIGHT = C.to("km / s").value
FILE_PREFIX = "class"
# FILE_EXTENSION = ".d2c" # OLD
FILE_EXTENSION = ".gdf" # OLD
DATA_EXTENSION = ".fits"

class DiscosScanException(Exception):
    def __init__(self, message):
        super(DiscosScanException, self).__init__(message)

class DiscosScanConverter(object):

    def __init__(self, path=None, duty_cycle={}, skip_calibration=False):
        self.SUMMARY=glob.glob(path+'?um*.fits')
        self.scan_path = path
        self.got_summary = False
        self.file_class_out = pyclassfiller.ClassFileOut()
        self.subscans = []
        self.duty_cycle = duty_cycle
        self.duty_cycle_size = sum(self.duty_cycle.values())
        self.n_cycles = 0
        self.integration = 0
        self.skip_calibration = skip_calibration
        
        self.feeds = []
        self.type = ""
        self.section_current_val = "" # trick for Sardara Nodding

        self.backend_name = "" # i.e. [sar] "sardara" or [ska] "skarab". The value will be used to discriminate the type of data processing according to the backend 

        self.scan_cycle_index = 0

    def skarab_duty_cycle(self):
       
            self.duty_cycle['sig'] = self.duty_cycle['sig'] * 2
            self.duty_cycle['on'] = self.duty_cycle['on'] * 2
            self.duty_cycle['off'] = self.duty_cycle['off'] * 2
            self.duty_cycle['cal'] = self.duty_cycle['cal'] * 2
            # update duty_cycle size:
            self.duty_cycle_size = sum(self.duty_cycle.values())


    def load_subscans(self):

        for subscan_file in os.listdir(self.scan_path):
            ext = os.path.splitext(subscan_file)[-1]
            if subscan_file.lower().startswith('sum'):
                self.SUMMARY=subscan_file
                logger.debug("Summary File: %s" % self.SUMMARY)
                

        
            if not subscan_file == self.SUMMARY and ext == DATA_EXTENSION:
                subscan_path = os.path.join(self.scan_path, subscan_file)
                with fits.open(subscan_path) as subscan:
                    self.subscans.append((subscan_path, 
                                          subscan[0].header["SIGNAL"],
                                          Time(subscan["DATA TABLE"].data["time"][0],
                                               format = "mjd",
                                               scale = "utc")
                                         ))

        # Before sorting the subscans in time, the backend name must be retrieved
        # Backend name can be retrieved in two ways: [A] from the summary dict or [B] from the file name
        # [A] self.backend = summary_header["BackendName"] or self.backend_name = summary_header["BackendName"][:3]
        # [B] If the file name contains the substr "FEED_" then the backend is "skarab", otherwise "sardara"
        if("FEED_" in str(self.subscans[0][0])): # from "load_subscans" first index is the item number in the list, second index the value [0]=file name, [1] signal flag, [2]=time
            self.backend_name = "ska"
        else:
            self.backend_name = "sar"
        # for skarab case (nodding mode) we need to sort files into blocks
        # so that first duty cycle is for feed 0, second for feed 6 third for 0 and so on
        # If the list of filenames alternates between the of two feeds then it is a mess!
        # Before we should know how skarab writes data:
        # it writes a duty cycle for each feed orr writes file alternating the feed?
        # And what are the keys assigned for the second feed? 
        # for sardara we have to invert the sign of the key since sections of two feeds are merged together in one file fits
        # Operatively: we need to take "self.subscans.sort(key=lambda x:x[2])" remove files 1,3,5 ... till end length duty_cycle
        # then add the removed filenames after half of the same duty_cycle

        # Apply special sorting for the Skarab case
        # Scan files will be like f0-f6-f0-f6-f0........
        # It has to be created a duty-cycle block for each individual feed like |f0-f0-f0.....||f6-f6-f6.....||f0-f0-f0.....|......
        # Each block (case Nodding) contains the sequence of REFSIG, SIGNAL, REFERENCE, REFCAL
        # It is like to generate an alternate Position Switching mode becase each next block has a different feed value
        if(self.backend_name == "ska" and len(self.duty_cycle.keys()) == 4):
            logger.debug("Skarab backend detected. Applying special sorting on scan files...")
            # subscans should be sorted rather by internal time stamp as correct recording time (can differ from the disk rec time)
            # check this out once testing with real skarab data -> self.subscans.sort(key=lambda x:x[2])
            self.subscans.sort()
            #for i in range(len(self.subscans)):
            #    print(self.subscans[i][0])
            tmp_list = []
            # The Skarab duty_cycle_size is double than the Sardara one since feeds files are recorded independently 
            duty_cycle_size_sk = self.duty_cycle_size*2 # case Nodding [1:6:6:1]=14 *2 feeds
            cycles = int(len(self.subscans)/duty_cycle_size_sk)

            tmp_list = self.subscans[1::2] # extracts and copy all items with odd indexes
            del self.subscans[1::2] # del all items with odd indexes from the original list

            # Create blocks in the original list by adding all even items in the original list
            for i in range(0, cycles):
                for j in range(int(i*duty_cycle_size_sk/2), int(i*duty_cycle_size_sk/2) + int(duty_cycle_size_sk/2)):
                    self.subscans.insert(j + int(i*duty_cycle_size_sk/2) + int(duty_cycle_size_sk/2), tmp_list[j])

            for i in range(len(self.subscans)):
                print(self.subscans[i][0])

        else:
            #order file names by internal data timestamp
            self.subscans.sort(key=lambda x:x[2])

        #self.subscans.sort(key=lambda x: (x[2], x[0]))
        
        logger.debug("ordered files: %s" % (str([filename for filename,_,_ in
                                                self.subscans]),))
        with fits.open(os.path.join(self.scan_path, self.SUMMARY)) as summary:
            self.summary = summary[0].header
      
       
    def convert_subscans(self, dest_dir=None):
               
        # send data subscan, duty cycle size and scan number to an external class

        #print('***', len(self.subscans))
        #print('***', self.subscans[0][0]) # from "load_subscans" first index is the item number in the list, second index the value [0]=file name, [1] signal flag, [2]=time
        #print('***', self.duty_cycle_size)
        #print('***', len(self.subscans) / self.duty_cycle_size)

        # In case of Nodding and usage of the skarab backend, we need to double the numbers of the duty cycle
        # This because feeds data are recorded in separate files (i.e. 6 'on' -> 12 'on' (for the second feed flag is however opposite)) 
        # if backend is skarab (i.e. data not merged) and the mode is Nodding (4 keys values in the dictionary self.duty_cycle)
        if((len(self.duty_cycle.keys()) == 4) and (self.backend_name == 'ska')):
            #self.skarab_duty_cycle()
            pass

        self.dest_dir = dest_dir
        if not self.dest_dir:
            self.dest_dir = self.scan_path
        else:
            try:
                os.makedirs(self.dest_dir)
            except Exception as e:
                if not os.path.isdir(self.dest_dir):
                    logger.error("cannot create output dir: %s" % (self.dest_dir,))
                    sys.exit(1)

      
        for i in range(int(len(self.subscans) / self.duty_cycle_size)): 
            self.n_cycles += 1
    
            # set the current scan cycle value. Save the value after the write_observation function has the job completed        
            self.scan_cycle_index = i

            #print("self.n_cycles:", self.n_cycles)
            print("len(self.subscans)", len(self.subscans))
            print("self.duty_cycle_size", self.duty_cycle_size)

            scan_cycle = self.convert_cycle(i * self.duty_cycle_size, i)
            self.write_observation(scan_cycle, i * self.duty_cycle_size) 

    def convert_cycle(self, index, current_cycle):
        current_index = index

        #print("Current Cycle*** " , current_cycle)

        with fits.open(self.subscans[index][0]) as first_subscan:
            scan_cycle = ScanCycle(first_subscan["SECTION TABLE"].data, 
                                   self.duty_cycle, self.backend_name, current_cycle)
            #scan_cycle.setCurrentCycle(current_cycle)

            # Extract the feed information
            used_feeds = first_subscan["RF INPUTS"].data["feed"]
            self.feeds = used_feeds # For "spectra" type and Nodding mode, self.feeds will look like {0,0,6,6} for LCP and RCP
            # print("Feeds", self.feeds)

            # Extraxt whether the observation is "spectra" or "stokes" type
            # self.type = first_subscan["SECTION TABLE"].data["type"][0] # get the first element of the array
            #print("type", self.type)

        # The duty_cycle is a dictionary in this class
        # We need to count the number of keys of the dictionary
        # 3 keys -> Position Switching
        # 4 keys -> Nodding
        len(self.duty_cycle.keys())
        logger.debug("Number of Duty Cycle keys (from function 'convert_cycle') %d" % (len(self.duty_cycle.keys())))

        if(len(self.duty_cycle.keys()) == 4): # we add an additional key for the REFSIG nodding case
            for i in range(self.duty_cycle['sig']):
                with fits.open(self.subscans[current_index][0]) as spec:
                    scan_cycle.add_data_file(spec, "sig")
                current_index += 1
       
        for i in range(self.duty_cycle['on']):
            with fits.open(self.subscans[current_index][0]) as spec:
                scan_cycle.add_data_file(spec, "on")
            current_index += 1
        for i in range(self.duty_cycle['off']):
            with fits.open(self.subscans[current_index][0]) as spec:
                scan_cycle.add_data_file(spec, "off")
            current_index += 1
        for i in range(self.duty_cycle['cal']):
            with fits.open(self.subscans[current_index][0]) as spec:
                scan_cycle.add_data_file(spec, "cal")
            current_index += 1
        return scan_cycle
            
    # function called by "write_observation(self, scan_cycle, first_subscan_index):"
    def _load_metadata(self, section, polarization, index):
       
        with fits.open(self.subscans[index][0]) as subscan:
            self.location = (subscan[0].header["SiteLongitude"] * u.rad,
                        subscan[0].header["SiteLatitude"] * u.rad)
            self.location = (self.location[0].to(u.deg),
                             self.location[1].to(u.deg))
            self.ra = subscan[0].header["RightAscension"]
            self.dec = subscan[0].header["Declination"]
            self.observation_time = Time(subscan["DATA TABLE"].data["time"][0],
                                         format = "mjd",
                                         scale = "utc", 
                                         location = self.location)
            self.azimut=subscan["DATA TABLE"].data["az"][0]
            self.elevation=subscan["DATA TABLE"].data["el"][0]
            weather_param=subscan["DATA TABLE"].data["weather"][0]
            self.humidity=weather_param[0]  # relative umidity of the air
            self.tamb=weather_param[1]      # air temperature in Celsius
            self.pamb=weather_param[2]  #ambient pressure in millibar
            
            # get the receiver
            self.receiver = subscan[0].header["Receiver Code"][:1]
            # get the backend name from the ScheduleName keyword
            # self.backend = subscan[0].header["ScheduleName"].split('_')[1] # gets the name between the first two "_"
	    
            self.record_time = Time(subscan[0].header["DATE"], scale="utc")
            self.antenna = subscan[0].header["ANTENNA"]
            self.ScanID = subscan[0].header["SCANID"]
            self.SubScanID = subscan[0].header["SubScanID"]
            self.source_name = subscan[0].header["SOURCE"]

            # For SARDARA backend case:
            # The scancycle function will merge the two sections (one for each polarization LL, RR) 
            # For PS mode will have section = 0, polarization left, section = 0, polarization right
            # For NOD mode will have section = 0, polarization left, section = 0, polarization right, section = 2, polarization left, section = 2, polarization right
            # However, some parameters (f.e. bins and bandwidth) must be retrieved from each single section whose indexes are 0, 1, 2, 3 
            # Within this loop, we are missing therefore the indexes 1 and 3 but instead 0 and 2 are repeated two times
            # To overcome this issue, it is defined a variable "self.section_current_val" which will be updated any time at the end of the function
            # So: during the first loop the variable is declared NULL and nothing happens since the section = 0. At the end of the loop the variable gets the value of the section i.e. 0
            # In the second loop, the section value is still 0 which is the value of the variable. In this case the section value is augmentd by +1 and we can read data for section 1 
            if(section == self.section_current_val): 
                section = section + 1

            for sec in subscan["SECTION TABLE"].data:
                if sec["id"] == section:
                    self.bins = sec["bins"]
                    self.bandwidth = sec["bandwidth"]
            for rf in subscan["RF INPUTS"].data:
                if((rf["polarization"] == polarization) and 
                   (rf["section"] == section)):

                    self.frequency = rf["frequency"]
                    self.LO = rf["localOscillator"]

                    try:
                        self.calibrationMark = rf["calibrationMark"]
                    except:
                        #For retrocompatibility
                        self.calibrationMark = rf["calibratonMark"]
                    self.feed = rf["feed"]
            self.freq_resolution = self.bandwidth / float(self.bins)

            self.central_frequency = self.frequency + self.bandwidth / 2.0
            try:
                self.rest_frequency = self.summary["rest_frequency"][section]
            except:
                #Fallback procedure loading only first restfreq
                logger.warning("using the same rest frequency for each section")
                self.rest_frequency = self.summary["rest_frequency"][0]
            offsetFrequencyAt0 = 0
            if self.bins % 2 == 0:
                self.central_channel = self.bins / 2
                self.offsetFrequencyAt0 = -self.freq_resolution / 2.
            else:
                self.central_channel = (nchan / 2) + 1
                self.offsetFrequencyAt0 = 0

            # Update section_current_value
            self.section_current_val = section

    def write_observation(self, scan_cycle, first_subscan_index):

        # According to the mode (i.e. Position Switching or Nodding) create the specific output filename
        mode = "" # Position Switching = "_psw"; Nodding = "_nod"
        if(len(self.duty_cycle.keys())) == 3: # CASE: Position Switching
            mode = "_psw"
        else:
            mode = "_nod"

        onoffcal = scan_cycle.onoffcal()

        for sec_id, v in scan_cycle.data.items():

            for pol, data in v.items():

                # For Skarab case Nodding (one file per each feed), because of the current section Table structure we need to add +2 to the value of the sec_id
                # to read out ancialliary data for the secondary feed, as they are stored always in the raw index 2 and 3 
                if((self.backend_name == 'ska') and (mode == "_nod")):

                    print("write_observation - scan_cycle.getCurrentCycle()", scan_cycle.getCurrentCycle())
                    
                    if(int(scan_cycle.getCurrentCycle()) % 2 == 0):

                        print("Duty Cycle index relative to the Primary Feed")

                    else:

                        print("Duty Cycle index relative to the Secondary Feed")
                        # change to 2 the sec_id value
                        sec_id = 2
                    
                logger.debug("opened section %d pol %s" % (sec_id, pol))
                self._load_metadata(sec_id, pol, first_subscan_index)

                # This is the standard method used to create the output file name. Ex: 2024234_IC485_nod.gdf
                # outputfilename = self.observation_time.datetime.strftime("%Y%j") + \
                #    "_" + self.source_name + mode + FILE_EXTENSION

                # This method uses the self.scan_path value to create the output file name
                # Inside there are multiple scans (for ex: 350, each duty cycle 14 subscans in Fitzilla format)
                # The output file name is like: 20240821-051506-26-23-IC485_nod.gdf
                folders =  self.scan_path.split(os.sep) # an array containing the full path as separated folders
                outputfilename = folders[len(folders)-1] + mode + FILE_EXTENSION

                # Alternatively, using a full date-time format in the filename will produce a CLASS file for each duty cycle within the same observation
                # outputfilename = self.observation_time.datetime.strftime("%Y%m%d-%H%M%S") + \
                #                 "_" + self.source_name +\
                #                 mode + FILE_EXTENSION

                output_file_path = os.path.join(self.dest_dir, outputfilename)
                try: 
                    logger.debug("try to open file %s" % (output_file_path,))
                    self.file_class_out.open(output_file_path,
                                             new = False,
                                             over = False,
                                             size = 999999,
                                             single = False)
                    logger.info("append observation to file %s" % (output_file_path,))
                except:
                    self.file_class_out.open(output_file_path,
                                             new = True,
                                             over = False,
                                             size = 999999,
                                             single = False)
                    logger.info("open new file %s" % (output_file_path,))

                # on, off, cal = onoffcal[sec_id][pol]
                
                obs = pyclassfiller.ClassObservation() 
                
                obs.head.presec[:]            = False  # Disable all sections except...
                obs.head.presec[code.sec.gen] = True  # General
                obs.head.presec[code.sec.pos] = True  # Position
                obs.head.presec[code.sec.spe] = True  # Spectral observatins  Activate always spectral section to include the name of the line 
                obs.head.presec[code.sec.cal] = True  # calibration observatins  Activate always spectral section to include the name of the line 

                obs.head.gen.num = 0
                obs.head.gen.ver = 0
                # obs.head.gen.teles = self.antenna + " " + "Feed [" + str(self.feeds[sec_id]) + "]" old
                obs.head.gen.teles = self.antenna + "-" + str(self.receiver) + "-" + self.summary['backendname'] + "-" + self.get_pol_type_string_converted(pol)
                obs.head.gen.dobs = int(self.observation_time.mjd) - 60549
                obs.head.gen.dred = int(self.record_time.mjd) - 60549
                obs.head.gen.typec = code.coord.equ
                obs.head.gen.kind = code.kind.spec
                obs.head.gen.qual = code.qual.unknown
                obs.head.gen.scan = self.ScanID
                obs.head.gen.subscan = self.SubScanID
                obs.head.gen.ut = (self.observation_time.mjd - int(self.observation_time.mjd)) * np.pi * 2
                #FIXME: get sidereal time right
                #obs.head.gen.st = observation_time.sidereal_time()
                obs.head.gen.st = 0.
                obs.head.gen.az = self.azimut  # unit radians
                obs.head.gen.el = self.elevation # radians
                obs.head.gen.tau = 0.
                #FIXME: should we read antenna temperature?
                obs.head.gen.time = data["on"][0]["integration"]
                obs.head.gen.xunit = code.xunit.freq  # Unused

                obs.head.pos.sourc = self.source_name
                obs.head.pos.epoch = 2000.0
                obs.head.pos.lam = self.ra
                obs.head.pos.bet = self.dec
                obs.head.pos.lamof = 0.
                obs.head.pos.betof = 0.
                obs.head.pos.proj = code.proj.none
                obs.head.pos.sl0p = 0. #FIXME: ?	
                obs.head.pos.sb0p = 0. #FIXME: ?	
                obs.head.pos.sk0p = 0. #FIXME: ?
   
                obs.head.cal.tamb=float(self.tamb+273.15) # must be in K 
                obs.head.cal.pamb=float(self.pamb)
                
                logger.debug("Air temperature  %f Air pressure %f" %  (self.tamb+273.15, self.pamb))

                obs.head.spe.restf = self.rest_frequency
                obs.head.spe.nchan = self.bins
                obs.head.spe.rchan = self.central_channel
                logger.debug("central channel  %f" %  self.central_channel)

                obs.head.spe.fres = self.freq_resolution 

                obs.head.spe.foff = self.offsetFrequencyAt0
                logger.debug("offset at 0  %f" %  self.offsetFrequencyAt0)

                obs.head.spe.vres = - (self.freq_resolution / self.central_frequency) * CLIGHT # frequency resolution must have the same unity like the central_frequency
                obs.head.spe.voff = self.summary["velocity"]["vrad"]
                obs.head.spe.bad = 0.
                obs.head.spe.image = 0.
                if self.summary["velocity"]["vframe"] == "BARY":
                    logger.debug("velocity: HELIO")
                    obs.head.spe.vtype = code.velo.helio
                elif((self.summary["velocity"]["vframe"] == "LSRK") or
                   (self.summary["velocity"]["vframe"] == "LSRD")):
                    obs.head.spe.vtype = code.velo.lsr
                    logger.debug("velocity: LSR")
                elif self.summary["velocity"]["vframe"] == "TOPCEN":
                    obs.head.spe.vtype = code.velo.obs
                    logger.debug("velocity: OBS")
                else:
                    obs.head.spe.vtype = code.velo.unk
                    logger.debug("velocity: UNK")
                v_observer = -((self.central_frequency - self.rest_frequency) /
                                          self.rest_frequency) * CLIGHT
                obs.head.spe.doppler = -  (v_observer + obs.head.spe.voff) / CLIGHT #doppler in units of c light
                                        #the negative sign is a class convention. 
                logger.debug("Doppler  %f" %  obs.head.spe.doppler)
                # get the pol type string converted
                pol_converted = self.get_pol_type_string_converted(pol)
                #obs.head.spe.line = "SEC%d-%s" % (sec_id, pol_converted) # old
                #obs.head.spe.line = "F%s-%s" % (str(self.feeds[sec_id]), str(self.bandwidth)) + " " + str(sec_id)
                obs.head.spe.line = "F%s-%s" % (str(self.feeds[sec_id]), str(self.bandwidth))
                
                # Check if data are relative to type=spectra 
                # If so check the number of feeds used: if n > 1 then nodding mode is applied
                # Then for the second feed, on and off values must be treated as REFERENCE and SIGNAL respectively 

                # Check the number of self.duty_cycle.keys()
                # If n = 3 -> Position Switching
                # If n = 4 -> Nodding

                # For Skarab Nodding, we need to restore the sec_id values 
                # since for each feed, relative raw data are stored in the sec_id = 0  
                if((self.backend_name == 'ska') and (mode == "_nod")):
                    sec_id = 0

                if(len(self.duty_cycle.keys())) == 3:
                    on, off, cal = onoffcal[sec_id][pol]
                else:
                    sig, on, off, cal = onoffcal[sec_id][pol]
                
                #print("Data for", sec_id, pol)
                #print("on", on[5140:5150])
                #print("off", off[5140:5150])
                #print("cal", cal[5140:5150])
                #print("sig", sig[5140:5150])

                #print(self.skip_calibration)
                #print(cal is not None)
               
                if((not self.skip_calibration) and 
                   (cal is not None)):
                    start_bin = int(self.bins / 3)
                    stop_bin = 2 * start_bin

                    if(len(self.duty_cycle.keys())) == 4: # compute sig_mean for the nodding case
                        sig_mean = sig[start_bin:stop_bin].mean()
                    cal_mean = cal[start_bin:stop_bin].mean()
                    off_mean = off[start_bin:stop_bin].mean()

                    # The "counts2kelvin" parameter is calculated differently according to the mode used
                    # Position Switching makes use of "cal_mean" values
                    # Nodding makes use of "cal_mean" values for the central feed (sections 0, 1) and "sig_mean" values for the second feed (sections 2, 3)
                
                    if(len(self.duty_cycle.keys())) == 3: # CASE: Position Switching
                        counts2kelvin = self.calibrationMark / (cal_mean - off_mean)
                    
                    if(len(self.duty_cycle.keys())) == 4:  # CASE: Nodding
                        if(sec_id == 0):
                            # counts2kelvin = self.calibrationMark / (sig_mean - off_mean)    
                            counts2kelvin = self.calibrationMark / (cal_mean - off_mean)    
                        else:
                            # counts2kelvin = self.calibrationMark / (cal_mean - off_mean)
                            counts2kelvin = self.calibrationMark / (sig_mean - off_mean)
                    
                    logger.debug("section_id: %f" % sec_id)
                    logger.debug("pol: %s" % pol,)
                    if(len(self.duty_cycle.keys())) == 4:
                        logger.debug("sig_mean: %f" % sig_mean)
                    logger.debug("cal_mean: %f" % cal_mean)
                    logger.debug("off_mean: %f" % off_mean,)
                    logger.debug("calibrationMark: %f" % self.calibrationMark)
                    logger.debug("c2k: %f" % (counts2kelvin,))
                    tsys = counts2kelvin * off_mean
                    obs.head.gen.tsys = tsys
                    logger.debug("tsys: %f" % (tsys,))

                    print(on)
                    print(off)
                   
                    obs.datay = ((on - off) / off ) * tsys # obs.datay has TYPE <class 'numpy.ndarray'>
                   
                else:
                    logger.debug("skip calibration")
                    obs.head.gen.tsys = 1. # ANTENNA TEMP TABLE is unknown
                    
                    obs.datay = ((on - off) / off )

                # Class needs numbers with some decimal digits
                # 0. is therefore not allowed and would a blanck histo bar in the graph
                # 0. must be converted for example to 0.00000000001 as declaring the single array lelemnts as 0.0000 won't work
                # This beacuse numerically, a float number 17. is equivalent to 17.0000. 
                # It is only a metter of how data are displayed  
                # 
                # From the dataset obs.datay (16384 channels), at first, we detect all the items with value 0.
                # Next we associate a value of 0.00000000001 to these values
                # Since class procedes graphs with 4 decimal digits, all cvalues will be truncated and rounded and 0.00000000001 will be 0.0000    

                zeros = np.where(obs.datay == 0.0)[0]
                # print(zeros)
                
                for i in range(len(zeros)):
                    #obs.datay[zeros[i]] = 0.00000000001
                    obs.datay[zeros[i]] = int(0.)

                #print(obs.head.spe.line)
                #print(obs.head.gen.teles)

                #print(len(obs.datay))
                #print(obs.datay[0:100])

                #print("Final data", obs.datay[21:30])
                #print("Final data", obs.datay[5140:5150])

                obs.write()
                self.file_class_out.close() 

                # save the current scan cycle value to disk
                with open('scan_cycle.txt', 'w') as output:
                    output.write(str(int(self.scan_cycle_index)+1))

    def load_summary_info(self, summary_file_path=None):
        if not summary_file_path:
            dir_name = self.scan_path
        summary_file_path = os.path.join(dir_name, self.SUMMARY)
        if not os.path.exists(summary_file_path):
            raise DiscosScanException("scan %s does not conatain a %s" % (dir_name,
                                                                          self.SUMMARY))
        with fits.open(summary_file_path) as summary_file:
            logger.debug("loading summary from %s" % (summary_file_path,))
            summary_header = summary_file[0].header
            rest_frequency = []
            index_restfreq = 1
            while summary_header.get("RESTFREQ%d" % (index_restfreq,)):
                rest_frequency.append(summary_header.get("RESTFREQ%d" %
                                                         (index_restfreq,)))
                index_restfreq += 1
            logger.debug("got rest freq: %s", str(rest_frequency))
            velocity = dict(vrad = summary_header["VRAD"],
                            vdef = summary_header["VDEF"],
                            vframe = summary_header["VFRAME"])

            # Backend name can be retrieved in two ways: [A] from the summary dict or [B] from the file name
            # [A] self.backend = summary_header["BackendName"] or self.backend_name = summary_header["BackendName"][:3]
            # [B] If the file name contains the substr "FEED_" then the backend is "skarab", otherwise "sardara"
            if("FEED_" in str(self.subscans[0][0])): # from "load_subscans" first index is the item number in the list, second index the value [0]=file name, [1] signal flag, [2]=time
                self.backend_name = "ska"
            else:
                self.backend_name = "sar"


        self.summary = (dict(rest_frequency = rest_frequency,
                             velocity = velocity,
                             backendname = summary_header["BackendName"][:3]))
        self.got_summary = True

    def get_pol_type_string_converted(self, pol):

        pol_type_converted = ""
        if(pol == "LCP"):
            pol_type_converted = "LL"
        if(pol == "RCP"):
            pol_type_converted = "RR"
        if(pol == "Q"):
            pol_type_converted = "LR"
        if(pol == "U"):
            pol_type_converted = "RL"

        return pol_type_converted
