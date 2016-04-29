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

import os
import logging
logger = logging.getLogger(__name__)
from datetime import datetime
import sys

import numpy as np 

from astropy.io import fits
from astropy import units as u
from astropy.time import Time
from astropy.constants import c as C

import pyclassfiller
from pyclassfiller import code

from scancycle import ScanCycle

SUMMARY = "summary.fits"
STOKES = "stokes"
CLIGHT = C.to("km / s").value
FILE_PREFIX = "class"
FILE_EXTENSION = ".d2c"
DATA_EXTENSION = ".fits"

class DiscosScanException(Exception):
    def __init__(self, message):
        super(DiscosScanException, self).__init__(message)

class DiscosScanConverter(object):
    def __init__(self, path=None, duty_cycle={}, skip_calibration=False):
        self.scan_path = path
        self.got_summary = False
        self.file_class_out = pyclassfiller.ClassFileOut()
        self.subscans = []
        self.duty_cycle = duty_cycle
        self.duty_cycle_size = sum(self.duty_cycle.values())
        self.n_cycles = 0
        self.integration = 0
        self.skip_calibration = skip_calibration

    def load_subscans(self):
        for subscan_file in os.listdir(self.scan_path):
            ext = os.path.splitext(subscan_file)[-1]
            if not subscan_file == SUMMARY and ext == DATA_EXTENSION:
                subscan_path = os.path.join(self.scan_path, subscan_file)
                with fits.open(subscan_path) as subscan:
                    self.subscans.append((subscan_path, 
                                          subscan[0].header["SIGNAL"],
                                          Time(subscan["DATA TABLE"].data["time"][0],
                                               format = "mjd",
                                               scale = "utc")
                                         ))
        #order file names by internal data timestamp
        self.subscans.sort(key=lambda(x):x[2])
        logger.debug("ordered files: %s" % (str([filename for filename,_,_ in
                                                  self.subscans]),))
        with fits.open(os.path.join(self.scan_path, SUMMARY)) as summary:
            self.summary = summary[0].header

    def convert_subscans(self, dest_dir=None):
        if not dest_dir:
            dest_dir = self.scan_path
        dest_subdir_name = os.path.normpath(self.scan_path).split(os.path.sep)[-1]
        dest_subdir_name += "_class"
        self.dest_subdir = os.path.join(dest_dir, dest_subdir_name)
        try:
            os.makedirs(self.dest_subdir)
        except Exception, e:
            logger.error("output directory exists: %s" % (self.dest_subdir,))
            sys.exit(1)
        for i in range(len(self.subscans) / self.duty_cycle_size):
            self.n_cycles += 1
            scan_cycle = self.convert_cycle(i * self.duty_cycle_size)
            self.write_observation(scan_cycle, i * self.duty_cycle_size)

    def convert_cycle(self, index):
        current_index = index
        with fits.open(self.subscans[index][0]) as first_subscan:
            scan_cycle = ScanCycle(first_subscan["SECTION TABLE"].data, 
                                   self.duty_cycle)
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
	    
            self.record_time = Time(subscan[0].header["DATE"], scale="utc")
            self.antenna = subscan[0].header["ANTENNA"]
            self.ScanID = subscan[0].header["SCANID"]
            self.SubScanID = subscan[0].header["SubScanID"]
            self.source_name = subscan[0].header["SOURCE"]
            for sec in subscan["SECTION TABLE"].data:
                if sec["id"] == section:
                    self.bins = sec["bins"]
            for rf in subscan["RF INPUTS"].data:
                if((rf["polarization"] == polarization) and 
                   (rf["section"] == section)):
                    self.frequency = rf["frequency"]
                    self.bandwidth = rf["bandwidth"]

                    self.LO = rf["localOscillator"]
                    try:
                        self.calibrationMark = rf["calibrationMark"]
                    except:
                        #For retrocompatibility
                        self.calibrationMark = rf["calibratonMark"]
                    self.feed = rf["feed"]
            self.freq_resolution = self.bandwidth / float(self.bins)

            self.central_frequency = self.frequency + self.bandwidth / 2.0
            offsetFrequencyAt0 = 0
            if self.bins % 2 == 0:
                self.central_channel = self.bins / 2
                self.offsetFrequencyAt0 = -self.freq_resolution / 2.
            else:
                self.central_channel = (nchan / 2) + 1
                self.offsetFrequencyAt0 = 0

    def write_observation(self, scan_cycle, first_subscan_index):
        onoffcal = scan_cycle.onoffcal()
        for sec_id, v in scan_cycle.data.iteritems():
            for pol, data in v.iteritems():
                logger.debug("opened section %d pol %s" % (sec_id, pol))
                self._load_metadata(sec_id, pol, first_subscan_index)

                outputfilename = self.observation_time.datetime.strftime("%Y%m%d-%H%M%S") + \
                                 "_" + self.source_name +\
                                 "_SCAN" + str(self.ScanID) + \
                                 "_SEC" + str(sec_id) + \
                                 "_" + str(pol) + \
                                 FILE_EXTENSION
                output_file_path = os.path.join(self.dest_subdir, outputfilename)
                self.file_class_out.open(output_file_path,
                                         new = True,
                                         over = True,
                                         size = 999999,
                                         single = True)

                obs = pyclassfiller.ClassObservation()
                obs.head.presec[:]            = False  # Disable all sections except...
                obs.head.presec[code.sec.gen] = True  # General
                obs.head.presec[code.sec.pos] = True  # Position
                obs.head.presec[code.sec.spe] = True  # Spectral observatins  Activate always spectral section to include the name of the line 
                obs.head.gen.num = 0
                obs.head.gen.ver = 0
                obs.head.gen.teles = self.antenna
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

                obs.head.spe.restf = self.summary["rest_frequency"]
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
                
                v_observer = -((self.central_frequency - self.summary["rest_frequency"]) /
                                          self.summary["rest_frequency"]) * CLIGHT
                
                
                obs.head.spe.doppler = -  (v_observer + obs.head.spe.voff) / CLIGHT #doppler in units of c light
                                        #the negative sign is a class convention. 
                
                
		logger.debug("Doppler  %f" %  obs.head.spe.doppler)

                obs.head.spe.line = "SEC%d-%s" % (sec_id, pol)

                on, off, cal = onoffcal[sec_id][pol]
                if((not self.skip_calibration) and 
                   (cal is not None)):
                    start_bin = self.bins / 3
                    stop_bin = 2 * start_bin
                    cal_mean = cal[start_bin:stop_bin].mean()
                    off_mean = off[start_bin:stop_bin].mean()
                    counts2kelvin = self.calibrationMark / (cal_mean - off_mean)
                    logger.debug("c2k: %f" % (counts2kelvin,))
                    tsys = counts2kelvin * off_mean
                    obs.head.gen.tsys = tsys
                    logger.debug("tsys: %f" % (tsys,))
                    obs.datay = (on - off) * (tsys / off_mean)
                    logger.debug("on - off: %f" % ((on - off).mean(),))
                else:
                    logger.debug("skip calibration")
                    obs.head.gen.tsys = 0. # ANTENNA TEMP TABLE is unknown
                    obs.datay = (on - off) / off
                obs.write()
                self.file_class_out.close()

    def load_summary_info(self, summary_file_path=None):
        if not summary_file_path:
            dir_name = self.scan_path
        summary_file_path = os.path.join(dir_name, SUMMARY)
        if not os.path.exists(summary_file_path):
            raise DiscosScanException("scan %s does not conatain a %s" % (dir_name,
                                                                          SUMMARY))
        with fits.open(summary_file_path) as summary_file:
            logger.debug("loading summary from %s" % (summary_file_path,))
            summary_header = summary_file[0].header
            rest_frequency = summary_header["RESTFREQ1"]
            #rest_frequency = [summary_header[ri] # * u.MHz
            #                  for ri in summary_header.keys() 
            #                  if ri.startswith("RESTFREQ")]
            velocity = dict(vrad = summary_header["VRAD"],
                            vdef = summary_header["VDEF"],
                            vframe = summary_header["VFRAME"])
        self.summary = (dict(rest_frequency = rest_frequency,
                             velocity = velocity))
        self.got_summary = True


