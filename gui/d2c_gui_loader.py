from astropy.io import fits
from astropy.time import Time
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QMainWindow, QApplication
from PyQt5.QtCore import pyqtSignal
from PyQt5.uic import loadUi
from tkinter import filedialog

import os
import threading
import time
import subprocess 
import sys

# Some defined constants
DATA_EXTENSION = ".fits"
# Some defined constants for combo-boxes
DUTY_CYCLE_VALUES = ['0','1','2','3','4','5','6','7','8','9']
MODE_TYPE = ['Position Switching', 'Nodding']
BACKEND_TYPE = ['Sardara', 'Skarab']

class MainUI(QMainWindow):

    updateText = pyqtSignal(str)   # Required to update the QplainTextArea widget during the gui thread
    insertText = pyqtSignal(str) 
    updateChrText = pyqtSignal(object)

    duty_cycle_size = 0 # default value. Any time any combo box is changed, the value is updated and the verify button disabled
    scan_cycles = [] # an array containing the number of scan cycles per each folder
    scan_cycle = 0 # the current scan cycle under processing
    backend_name = ""

    subdirs = []

    p_returncode = 0  
    p_stderr = ""
    p_stdout = ""

    progress_timer = True

    verify_result = [None]*4 # it contains the result of the duty cycle check 



    def __init__(self):
        super(MainUI, self).__init__()

        loadUi("d2c_gui.ui", self)

        # Define the character format attributes for the QplainTextArea widget
        self.color_format_std =  self.info_panel_ta.currentCharFormat() # standard format
        self.color_format_hld =  self.info_panel_ta.currentCharFormat() # high-lighted format
        self.color_format_err =  self.info_panel_ta.currentCharFormat() # error format

        self.color_hld = QColor(25, 160, 194, 255) # R,G,B,Opacity for high-lighted format 
        self.color_format_hld.setForeground(self.color_hld)
        self.color_format_hld.setFontWeight(QFont.Bold)

        self.color_err = QColor(255, 0, 0, 255) # R,G,B,Opacity for error format 
        self.color_format_err.setForeground(self.color_err)
        self.color_format_err.setFontWeight(QFont.Bold)

        # Set hld format for the QplainTextArea widget
        self.info_panel_ta.setCurrentCharFormat(self.color_format_hld)
        # Make the text area read-only
        self.info_panel_ta.setReadOnly(True)
        
        self.info_panel_ta.appendPlainText('*** Welcome to d2c Converter [GUI Mode - v. 0.1] ***')
        self.info_panel_ta.appendPlainText("")

        # Set std format for the QplainTextArea widget
        self.info_panel_ta.setCurrentCharFormat(self.color_format_std)
        
        # Update the QplainTextArea widget during the gui thread
        self.updateText.connect(self.info_panel_ta.appendPlainText)
        self.insertText.connect(self.info_panel_ta.insertPlainText)
        self.updateChrText.connect(self.info_panel_ta.setCurrentCharFormat)

        # Fix dimensions of the QMainWindow widget
        self.setFixedSize(1000, 380)
        # self.centralwidget.setFixedSize(800,441)

        # adding the duty cycle values to the relative combo boxes
        self.duty_cycle_cmb0.addItems(DUTY_CYCLE_VALUES)
        self.duty_cycle_cmb1.addItems(DUTY_CYCLE_VALUES)
        self.duty_cycle_cmb2.addItems(DUTY_CYCLE_VALUES)
        self.duty_cycle_cmb3.addItems(DUTY_CYCLE_VALUES)

        #  adding action to combo box duty cycle values 
        self.duty_cycle_cmb0.activated.connect(self.set_duty_cycle_size)
        self.duty_cycle_cmb1.activated.connect(self.set_duty_cycle_size)
        self.duty_cycle_cmb2.activated.connect(self.set_duty_cycle_size)
        self.duty_cycle_cmb3.activated.connect(self.set_duty_cycle_size)

        # adding mode-type list to the relative combo box
        self.mode_cmb.addItems(MODE_TYPE)
        self.backend_cmb.addItems(BACKEND_TYPE)
        self.backend_cmb.setDisabled(True)

        #  adding action to combo box mode type (Position Switching, Nodding) 
        self.mode_cmb.activated.connect(self.switch_duty_cycles)

        # 'convert' and 'verify' button are disabled until both source and destination folders are selected 
        self.convert_btn.setDisabled(True)
        self.verify_btn.setDisabled(True)
        
        # Buttons and Combos functions
        self.source_folder_btn.clicked.connect(self.select_source_folder)
        self.destination_folder_btn.clicked.connect(self.select_destination_folder)
        self.verify_btn.clicked.connect(self.verify_btn_handler)
        self.convert_btn.clicked.connect(self.convert_btn_handler)
        self.duty_cycle_cmb3.currentIndexChanged.connect(self.disable_convert_btn)
        self.duty_cycle_cmb1.currentIndexChanged.connect(self.disable_convert_btn)
        self.duty_cycle_cmb2.currentIndexChanged.connect(self.disable_convert_btn)
        self.duty_cycle_cmb0.currentIndexChanged.connect(self.disable_convert_btn)
        self.mode_cmb.currentIndexChanged.connect(self.disable_convert_btn)
        self.calibration_cb.clicked.connect(self.disable_convert_btn)

        # Define variables hosting the source and destination folder path values
        self.source_folder = ""
        self.destination_folder = ""

        # ProgressBar
        self.progressBar.setValue(0)

   
    def disable_all_widgets(self, value):

        self.source_folder_btn.setDisabled(value)
        self.destination_folder_btn.setDisabled(value)
        self.verify_btn.setDisabled(value)
        self.convert_btn.setDisabled(value)
        self.duty_cycle_cmb3.setDisabled(value)
        self.duty_cycle_cmb1.setDisabled(value)
        self.duty_cycle_cmb2.setDisabled(value)
        if(self.mode_cmb.currentText() == 'Nodding'):
            self.duty_cycle_cmb0.setDisabled(value)
        self.calibration_cb.setDisabled(value)
        self.mode_cmb.setDisabled(value)

    def set_duty_cycle_size(self):

        self.duty_cycle_size = int(self.duty_cycle_cmb0.currentText()) + int(self.duty_cycle_cmb1.currentText()) + int(self.duty_cycle_cmb2.currentText()) + int(self.duty_cycle_cmb3.currentText())
        self.enable_verify_btn()

    def get_duty_cycle_size(self):

        return int(self.duty_cycle_size)

        
    def switch_duty_cycles(self):
        # Activete or deactivare the first duty_cycle_cb according to the mode selected (PS:3, ND:4)
        if(self.mode_cmb.currentText() == 'Position Switching'):
            self.duty_cycle_cmb0.setCurrentIndex(0) 
            self.duty_cycle_cmb0.setDisabled(True)
        else:
            self.duty_cycle_cmb0.setDisabled(False)
    
    def select_source_folder(self):

        self.verify_btn.setDisabled(True)
        self.convert_btn.setDisabled(True)
        self.source_folder = filedialog.askdirectory()
        if(self.source_folder):
            self.info_panel_ta.setCurrentCharFormat(self.color_format_hld) 
            self.info_panel_ta.appendPlainText('SELECTED SOURCE FOLDER:')
            self.info_panel_ta.setCurrentCharFormat(self.color_format_std) 
            self.info_panel_ta.appendPlainText(self.source_folder)
            self.info_panel_ta.appendPlainText('')
            self.enable_verify_btn()
        else:
            self.info_panel_ta.setCurrentCharFormat(self.color_format_hld) 
            self.info_panel_ta.appendPlainText('SELECTED SOURCE FOLDER:')
            self.info_panel_ta.setCurrentCharFormat(self.color_format_std) 
            self.info_panel_ta.appendPlainText('Not specified')
            self.info_panel_ta.appendPlainText('')

    def select_destination_folder(self):
        
        self.verify_btn.setDisabled(True)
        self.convert_btn.setDisabled(True)
        self.destination_folder = filedialog.askdirectory()
        if(self.destination_folder):
            self.info_panel_ta.setCurrentCharFormat(self.color_format_hld) 
            self.info_panel_ta.appendPlainText('SELECTED DESTINATION FOLDER:')
            self.info_panel_ta.setCurrentCharFormat(self.color_format_std) 
            self.info_panel_ta.appendPlainText(self.destination_folder)
            self.info_panel_ta.appendPlainText('')
            self.enable_verify_btn()
        else:
            self.info_panel_ta.setCurrentCharFormat(self.color_format_hld) 
            self.info_panel_ta.appendPlainText('SELECTED DESTINATION FOLDER:')
            self.info_panel_ta.setCurrentCharFormat(self.color_format_std) 
            self.info_panel_ta.appendPlainText('Not specified')
            self.info_panel_ta.appendPlainText('') 

    def disable_convert_btn(self):

        self.convert_btn.setDisabled(True)
        

    def build_duty_cycle(self):

        duty_cycle = ''
        
        if(self.mode_cmb.currentText() == 'Position Switching'):

            duty_cycle = str(self.duty_cycle_cmb1.currentText()) + ':'  + str(self.duty_cycle_cmb2.currentText()) + ':' + str(self.duty_cycle_cmb3.currentText())
        else:
            duty_cycle = str(self.duty_cycle_cmb0.currentText()) + ':'  + str(self.duty_cycle_cmb1.currentText()) + ':' + str(self.duty_cycle_cmb2.currentText()) + ':' +  str(self.duty_cycle_cmb3.currentText())
        
        return duty_cycle

    def foo(self):

        if(self.progress_timer):
            print(time.ctime())

            try:
                f = open('scan_cycle.txt', 'r')
                self.scan_cycle = int(f.read()) 
                f.close()
                print(self.scan_cycle+1)
                self.progressBar.setValue(int(self.scan_cycle))
            
            except:
                pass

            t = threading.Timer(1, self.foo)
            t.start()
        
        else:

            try:
                # Read the last value for final update
                f = open('scan_cycle.txt', 'r')
                self.scan_cycle = int(f.read())    
                f.close()
                print(self.scan_cycle)
                self.progressBar.setValue(int(self.scan_cycle))
                # Reset the output file scan cycle value
                with open('scan_cycle.txt', 'w') as output:
                    output.write(str(0))
                print(time.ctime())
            
            except:
                pass

    def convert_btn_handler(self):

        #self.disable_all_widgets(True)
        duty_cycle = self.build_duty_cycle()

        self.disable_all_widgets(True)

        # Convert data for each subfolder
        for i in range(len(self.subdirs)):

            # Reset the progress bar and associate the scan_cycles to its max value 
            self.progressBar.reset()
            self.progressBar.setRange(0,self.scan_cycles[i])
            self.progressBar.setValue(0)
            
            self.progress_timer = True
            self.foo()

            self.info_panel_ta.repaint()
            self.info_panel_ta.appendPlainText('Please wait while data are being converted...')
            # self.info_panel_ta.appendPlainText('Folder: ' + self.subdirs[i])

            # executable_command = self.d2c_cmd_builder(self.debug_cb.isChecked(), duty_cycle, self.calibration_cb.isChecked(), self.version_cb.isChecked())
            executable_command = self.d2c_cmd_builder(duty_cycle, self.calibration_cb.isChecked(), self.subdirs[i])
            self.info_panel_ta.setCurrentCharFormat(self.color_format_hld) 
            self.updateText.emit('COMMAND TO BE EXECUTED:')
            self.info_panel_ta.setCurrentCharFormat(self.color_format_std) 
            self.info_panel_ta.appendPlainText(executable_command)
            # self.info_panel_ta.appendPlainText("")   
            self.info_panel_ta.repaint()
            #self.thread0 = threading.Thread(target=self.disable_all_widgets, args=(True,))
            #self.thread0.start()
            #self.thread0.join()

            self.thread = threading.Thread(target=self.exec_cmd, args=(executable_command,))
            self.thread.daemon = True # apparently it makes possible to update the GUI before executing the thread
            self.thread.start()
            self.thread.join()

            
            if self.p_returncode != 0:
            # handle error
                self.updateChrText.emit(self.color_format_err)
                self.updateText.emit('PROCESS RETURNED ERRORS')
                self.updateChrText.emit(self.color_format_std) 
                self.updateText.emit(self.p_stderr) # stderr is a byte object and must be converted
                self.updateText.emit(self.p_stdout) 
                self.info_panel_ta.repaint()
            else:
                self.updateChrText.emit(self.color_format_hld) 
                self.updateText.emit('PROCESS SUCCESSFULLY COMPLETED')
                self.updateChrText.emit(self.color_format_std) 
                self.updateText.emit("")
                self.info_panel_ta.repaint()
            
        self.disable_all_widgets(False)
        self.convert_btn.setDisabled(True)   
    
    def verify_btn_handler(self):
        
        file_error = False
        duty_cycle = self.build_duty_cycle()  

        self.scan_cycles.clear()
        
        self.info_panel_ta.setCurrentCharFormat(self.color_format_hld) 
        self.info_panel_ta.appendPlainText('PARAMETERS SUMMARY:')
        self.info_panel_ta.setCurrentCharFormat(self.color_format_std) 
        self.info_panel_ta.appendPlainText('Duty Cycle -> ' + duty_cycle)
        # self.info_panel_ta.appendPlainText('Debug -> ' + str(self.debug_cb.isChecked()))
        self.info_panel_ta.appendPlainText('Skip Calibration -> ' + str(self.calibration_cb.isChecked()))
        # self.info_panel_ta.appendPlainText('Version -> ' + str(self.version_cb.isChecked()))
        self.info_panel_ta.appendPlainText('Mode -> ' + str( self.mode_cmb.currentText()))
        # self.info_panel_ta.appendPlainText('Backend -> ' + str( self.backend_cmb.currentText()))
        # self.info_panel_ta.setCurrentCharFormat(self.color_format_hld)
        self.info_panel_ta.appendPlainText("")

        # Retrieve all subfolders, if any, from the selected folder
        self.create_subdirs()

        for i in range(len(self.subdirs)):  

            self.disable_all_widgets(True)

            #self.info_panel_ta.appendPlainText('Checking Duty-Cycle structure... ')   
            #self.info_panel_ta.appendPlainText('Folder: ' + self.subdirs[i])   

            self.updateText.emit('Checking Duty-Cycle structure... ')   
            self.updateText.emit('Folder: ' + self.subdirs[i])   

            self.info_panel_ta.repaint()

            self.thread = threading.Thread(target=self.check_duty_cycle, args=(self.subdirs[i],))
            self.thread.daemon = True # apparently it makes possible to update the GUI before executing the thread
            self.thread.start()
            self.thread.join() 
        
            
            if not (self.verify_result[0]):

                self.info_panel_ta.appendPlainText("[DONE]. Duty-cycle check successfully completed.")
                #self.info_panel_ta.insertPlainText('DONE. Ready to convert data!')
                self.info_panel_ta.appendPlainText("")
                self.disable_all_widgets(False)
                self.enable_convert_btn()
                
            else:
                # update QtextArea
                # self.info_panel_ta.insertPlainText('[DONE]. Duty-Cycle check ended with errors.')
                self.info_panel_ta.appendPlainText('[DONE]. Duty-Cycle check ended with errors.')
                #self.info_panel_ta.appendPlainText("")
                self.info_panel_ta.setCurrentCharFormat(self.color_format_err) 
                self.info_panel_ta.appendPlainText('Duty-Cycle #' + str(self.verify_result[1]))
                self.info_panel_ta.appendPlainText('File: ' + str(self.verify_result[2]))
                self.info_panel_ta.setCurrentCharFormat(self.color_format_std) 
                self.info_panel_ta.appendPlainText('')
                self.disable_all_widgets(False)
                self.disable_convert_btn()

        #print(self.scan_cycles)
            
           

    def check_duty_cycle(self, folder):

        # This method checks if the fits files contained in the source folder match the duty cycle structure

        subscans = [] # Each row conatins scan information about path, signal type and timestamp data 
        duty_cycle_flags = []
        error = False
        nfile_err = 0
        filename_err = ""

        mode = self.mode_cmb.currentText()
        duty_cycle_size = self.get_duty_cycle_size() 
       

        # At firt, build the 'duty_cycle_flags' structure
        
        # If the mode is Nodding then we start adding the REFSIG flag to the 'duty_cycle_flags'
        if(self.mode_cmb.currentText() == 'Nodding'):

            for i in range(int(self.duty_cycle_cmb0.currentText())):
                
                duty_cycle_flags.append('REFSIG')

        # Regardless of the mode (i.e. Position switching or Nodding) add the following flags to the 'duty_cycle_flags'

        for i in range(int(self.duty_cycle_cmb1.currentText())):
                
            duty_cycle_flags.append('SIGNAL')

        for i in range(int(self.duty_cycle_cmb2.currentText())):
                
            duty_cycle_flags.append('REFERENCE')

        for i in range(int(self.duty_cycle_cmb3.currentText())):
                
            duty_cycle_flags.append('REFCAL')
        
       
        #for subscan_file in os.listdir(self.source_folder):
        for subscan_file in os.listdir(folder):

            ext = os.path.splitext(subscan_file)[-1]

            if not subscan_file.lower().startswith('sum') and ext == DATA_EXTENSION:
                #subscan_path = os.path.join(self.source_folder, subscan_file)
                subscan_path = os.path.join(folder, subscan_file)

                with fits.open(subscan_path) as subscan:
                    subscans.append((subscan_path, 
                                    subscan[0].header["SIGNAL"],
                                    Time(subscan["DATA TABLE"].data["time"][0],
                                        format = "mjd",
                                        scale = "utc")
                ))
        
        # Before sorting the subscans in time, the backend name must be retrieved
        # Backend name can be retrieved in two ways: [A] from the summary dict or [B] from the file name
        # [A] self.backend = summary_header["BackendName"] or self.backend_name = summary_header["BackendName"][:3]
        # [B] If the file name contains the substr "FEED_" then the backend is "skarab", otherwise "sardara"
        if("FEED_" in str(subscans[0][0])): # from "load_subscans" first index is the item number in the list, second index the value [0]=file name, [1] signal flag, [2]=time
            self.backend_name = "ska"
        else:
            self.backend_name = "sar"

        if(self.backend_name == "ska" and mode == "Nodding"):
            # subscans should be sorted rather by internal time stamp as correct recording time (can differ from the disk rec time)
            # check this out once testing with real skarab data -> self.subscans.sort(key=lambda x:x[2])
            subscans.sort()
            #for i in range(len(self.subscans)):
            #    print(self.subscans[i][0])
            tmp_list = []
            # The Skarab duty_cycle_size is double than the Sardara one since feeds files are recorded independently 
            duty_cycle_size_sk = duty_cycle_size*2 # case Nodding [1:6:6:1]=14 *2 feeds
            cycles = int(len(subscans)/duty_cycle_size_sk)

            tmp_list = subscans[1::2] # extracts and copy all items with odd indexes
            del subscans[1::2] # del all items with odd indexes from the original list

            # Create blocks in the original list by adding all even items in the original list
            for i in range(0, cycles):
                for j in range(int(i*duty_cycle_size_sk/2), int(i*duty_cycle_size_sk/2) + int(duty_cycle_size_sk/2)):
                    subscans.insert(j + int(i*duty_cycle_size_sk/2) + int(duty_cycle_size_sk/2), tmp_list[j])

            # for i in range(len(subscans)):
            #    print(subscans[i][0])

        else:
            #order file names by internal data timestamp
            subscans.sort(key=lambda x:x[2])
        
        # Order fits file names by internal data timestamp
        # subscans.sort(key=lambda x:x[2])


        self.scan_cycles.append(int(len(subscans)/int(self.duty_cycle_size)))

        
        j = 0 # duty_cycle index
        d = 0 # duty_cycle current number
        
        self.progressBar.reset()
        self.progressBar.setRange(0,len(subscans))

        # Start fits file and duty cycle comparison
        for i in range(len(subscans)):

            self.progressBar.setValue(i+1)

            #self.info_panel_ta.repaint()
            #self.updateText.emit(str(int(i+1)) + '/' + str(len(subscans)))
            #self.info_panel_ta.repaint()
            time.sleep(0.05)
           
            #print(i)
            #print(subscans[i][1])
            #print(duty_cycle_flags[j])
        
            if(subscans[i][1] != duty_cycle_flags[j]): # in case of mismatch
            
                error = True
                nfile_err = i
                filename_err = subscans[i][0]

                self.verify_result[0] = error
                self.verify_result[1] = d
                self.verify_result[2] = filename_err
                self.verify_result[3] = folder                    
                break
            else:

                error = False

                self.verify_result[0] = error
                self.verify_result[1] = 0
                self.verify_result[2] = ""
                self.verify_result[3] = ""

            j = j + 1
            if(j == len(duty_cycle_flags)):

                j = 0
                d = d + 1

        '''
        if not error:

            self.insertText.emit('DONE. Ready to convert data!')
            self.updateText.emit("")
            self.disable_all_widgets(False)
            self.enable_convert_btn()
            
        else:
            # update QtextArea
            self.info_panel_ta.setCurrentCharFormat(self.color_format_err) 
            self.updateText.emit('Duty-Cycle ERROR #' + str(d) + ', File: ' + str(filename_err))
            self.info_panel_ta.setCurrentCharFormat(self.color_format_std) 
            self.updateText.emit('')
        '''
        
        # return error, d, filename_err
          
    def enable_convert_btn(self):
        if( (self.source_folder != "") and (self.destination_folder != "") and (self.duty_cycle_size != 0)):
            self.convert_btn.setDisabled(False)   
        else:
            self.convert_btn.setDisabled(True)

    def enable_verify_btn(self):
        if( (self.source_folder != "") and (self.destination_folder != "") and (self.duty_cycle_size != 0)):
            self.verify_btn.setDisabled(False)   
        else:
            self.verify_btn.setDisabled(True)
      
    def d2c_cmd_builder(self, duty_cycle, calibration, folder):

        cmd = "discos2class "
        #if(debug_mode):
        #    cmd = cmd + '-d '
        cmd = cmd + '-o ' + self.destination_folder + ' '
        cmd = cmd + '-c ' + duty_cycle + ' '
        if(calibration):
            cmd = cmd + '-s '
        #if(version):
        #    cmd = cmd + '--version '
        # cmd = cmd + self.source_folder
        cmd = cmd + folder
        
        return cmd

    def exec_cmd(self, executable_command):

        p = subprocess.Popen([executable_command], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        #p = subprocess.Popen(['designer'], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
       
        # To capture the error message:
        stdout, stderr = p.communicate()
        # stdout = normal output
        # stderr = error output

        #t.cancel()

        # p.terminate()
        self.progress_timer = False
        

        time.sleep(0.5)
        # self.convert_btn.setDisabled(False)
        
        if p.returncode != 0:

            self.p_returncode = p.returncode
            self.p_stderr = stderr.decode()
            self.p_stdout = stdout.decode()

    def create_subdirs(self):
        # Retrieve all subfolders, if any, from the selected folder
        self.subdirs.clear()

        d = self.source_folder
        for o in os.listdir(d):
            if os.path.isdir(os.path.join(d,o)): 
                if(('tmp' not in str(os.path.join(d,o))) and 'tempfits' not in str(os.path.join(d,o))):
                    self.subdirs.append(os.path.join(d,o))

        # Check if subdirs is empty. It means that the user selected a folder condaining data
        # In this case subdirs gets the value of self.source_folder
        if not self.subdirs:
            self.subdirs.append(self.source_folder)

        #subdirs = [os.path.join(d, o) for o in os.listdir(d) if os.path.isdir(os.path.join(d,o)) 
        #and not 'tmp' in os.path.isdir(os.path.join(d,o)) or 'tempfits' in os.path.isdir(os.path.join(d,o))]
        # subdirs = [x[0] for x in os.walk(self.source_folder)]
        self.subdirs.sort()
        print(self.subdirs)
    
        
if __name__ == "__main__":
    # The next line solves the issues of mismatch between designer sizes and monitor sizes
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    ui = MainUI()
    ui.show()
    app.exec_()


