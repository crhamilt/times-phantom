#!/usr/bin/env python3

# perform automated analysis of MR scans of the T1MES phantom

# this script is run by cron every day at 3am on aging2a

import os
import shutil
import glob
from email.mime.text import MIMEText
from subprocess import Popen, PIPE
import dicom
import isdicom
import meastimes

# this must be a full path
involume = '/bme007/cardhome2/UPBEAT/Images/QA_T1MES_Phantom/'
# involume = '/Users/crhamilt/box/py/myrepos/times_phantom/test_QA/'
indir = involume + 'incoming'
resultsdir = involume + 'results'
completedir = involume + 'completed'


def logit(ldate, lsite, lseries, lstat):
    print('Logging ', ldate, lsite, lseries, lstat)
    f = open(involume + 'QA.log', 'a')
    if stat == 0:
        f.write('%8s  %4s %4s       Success\n' % (ldate, lsite, lseries))
    else:
        f.write('%8s  %4s %4s       Fail\n' % (ldate, lsite, lseries))

    f.close()


def copy_results(rdir):
    print('copying from %s' % rdir)
    for file in glob.glob(os.path.join(rdir, '*contours.png')):
        print('copying %s to %s' % (file, resultsdir))
        shutil.copy(os.path.join(rdir, file), resultsdir)
    for file in glob.glob(os.path.join(rdir, '*info.csv')):
        shutil.copy(os.path.join(rdir, file), resultsdir)
    for file in glob.glob(os.path.join(rdir, '*results.json')):
        shutil.copy(os.path.join(rdir, file), resultsdir)


# from:  https://stackoverflow.com/questions/73781/sending-mail-via-sendmail-from-python
def sendmail(dname, mstat):
    msg = MIMEText("It was analyzed in " + dname)
    msg["From"] = "crhamilt@wakehealth.edu"
    msg["To"] = "crhamilt@wakehealth.edu"
    if mstat == 0:
        msg["Subject"] = "T1MES Phantom QA analysis complete: Success."
    else:
        msg["Subject"] = "T1MES Phantom QA analysis complete: Failure."

    p = Popen(["/usr/sbin/sendmail", "-t", "-oi"], stdin=PIPE, universal_newlines=True)
    p.communicate(msg.as_string())


#####################
#  main starts here
#####################

print('checking in ', indir)

# incoming scans should be in a PATIENTID/DATE/SERNUM folder hierarchy

firstpass = True
founddirs = []
stat = 1

for root, dirs, files in os.walk(indir):

    stat = 0  # status of analysis results from meastimes()
    if firstpass:
        print('root = %s' % root)
        print(f'dirs = {dirs}')
        founddirs = dirs
        firstpass = False

    for fname in files:
        fullname = os.path.join(root, fname)
        print('checking ', fullname)
        if fname.lower().endswith('dcm') and isdicom.isdcm(fullname):
            try:
                ds = dicom.read_file(fullname)
            except dicom.errors.InvalidDicomError:
                print('Bad DICOM')

            # create unique site/date identifier
            if "wake" in ds.InstitutionName.lower():
                site = 'Wake'
            elif "VCU" in ds.InstitutionName:
                site = 'VCU'
            else:
                site = 'Null'

            print('site = ', site)

            date = ds.StudyDate

            patid = ''
            if 'PatientID' in ds:
                patid = ds.PatientID
                
            if '152E' in patid or '302E' in patid:

                # print('found QA patientID: ',patid)

                sernum = ''
                if "SeriesNumber" in ds:
                    sernum = 'Ser %s' % ds.SeriesNumber
                    print('Checking series ', ds.SeriesNumber)

                serdescr = ''
                if "SeriesDescription" in ds:
                    serdescr = sernum+':'+ds.SeriesDescription
                elif "ProtocolName" in ds:
                    serdescr = sernum+':'+ds.ProtocolName

                vendor = ''
                if "Manufacturer" in ds:
                    vendor = ds.Manufacturer

                if vendor.lower().startswith('si'):
                    if 'MOCO_T1' in serdescr:
                        theimagefile = os.path.join(root, fname)
                        print('Found map: ', theimagefile)
                        stat = meastimes.meas_times(theimagefile, 0)
                        sendmail(root, stat)
                        logit(date, site, ds.SeriesNumber, stat)
                        if stat == 0:
                            copy_results(root)
                    else:
                        break

                elif vendor.lower().startswith('ph'):
                    if 'MID_SAX_T1_Map' in serdescr:
                        if ds.InstanceNumber == 11:
                            theimagefile = os.path.join(root, fname)
                            print('Found map: ', theimagefile)
                            stat = meastimes.meas_times(theimagefile, 0)
                            sendmail(root, stat)
                            logit(date, site, ds.SeriesNumber, stat)
                            if stat == 0:
                                copy_results(root)
                    else:
                        break

                elif vendor.lower().startswith('ge'):
                    if 'GET1' in serdescr:
                        theimagefile = os.path.join(root, fname)
                        stat = meastimes.meas_times(theimagefile, 0)
                        sendmail(root, stat)
                        logit(date, site, ds.SeriesNumber, stat)
                        if stat == 0:
                            copy_results(root)
                    else:
                        break


# move the study to ../completed
if stat == 0:
    for dd in founddirs:
        os.rename(os.path.join(indir, dd), os.path.join(indir, '../completed/' + dd))
        print('moved completed study to completed/' + dd)
