#!/usr/bin/env python3

# find tubes using Hough Transform, from docs.opencv.org tutorials

import sys
import os
import argparse
import dicom
import numpy as np
import csv
import json
from collections import OrderedDict
import cv2
import redcap_link

DEBUGPRINT = True


def dprint(*args0):
    if DEBUGPRINT:
        print(args0)

# to show the correct names to use for elements:
# print(dset.dir())
# sys.exit()

#
#  geometry info
#
#    we know the phantom is about 120x120 mm
#    if we assume the phantom is centered on isocenter,
#    then we can determine the pixel boundaries expected
#    in a image with an arbitrary FOV and pixel size
#
#    we want to go a bit less than +/- 60 mm from the center
#    use dset.PixelSpacing to determine how many pixels in 60mm
#    use dset.Rows/Columns to find center pixel
#
#    IMPORTANT NOTE:  opencv uses coordinates as [y,x] !!


def meas_times(img, showit):

    dset = dicom.read_file(img, force=True)
    imp = dset.pixel_array
    dprint('imp shape =', imp.shape)
    dprint('imp dtype =', imp.dtype)

    mm2pix = 1/dset.PixelSpacing[0]
    pix_half = 60*mm2pix

    cx = dset.Columns/2
    cy = dset.Rows/2
    x0 = int(cx - pix_half)
    x1 = int(cx + pix_half)
    y0 = int(cy - pix_half)
    y1 = int(cy + pix_half)

    dprint('cx,cy = ', cx, cy)
    dprint('x0,y0 = ', x0, y0)
    dprint('x1,y1 = ', x1, y1)

    # crop to just the phantom   [Y,X]
    # imp = imp[43:105, 66:127]
    imp = imp[y0:y1, x0:x1]
    imp = cv2.resize(imp, (256, 256))
    
    # by resizing, the mm-to-pixel conversion changes
    mm2pix = mm2pix * 256/(x1-x0)

    # some routines don't work with 16bit images, so rescale and convert to 8bit
    img8 = (imp/10).astype(np.uint8)

#    dprint('img8 shape =', img8.shape)
#    dprint('img8 dtype =', img8.dtype)
#    cv2.imshow("img8", img8)

    # blur a bit to remove noise 
    img8b = cv2.GaussianBlur(img8, (9, 9), 0)

    if showit:
        cv2.imshow("img8b", img8b)

    # tubes are around 30mm in diameter, so set min/max Radius
    #   in pixels
    minrad = int(13*mm2pix)
    maxrad = int(18*mm2pix)
    #  tubes are about 35mm apart
    mindist = int(32*mm2pix)
    # param1: gradient value, use default
    # param2: threshold, use default
    circles = cv2.HoughCircles(img8, cv2.HOUGH_GRADIENT, 1, mindist,
                               param1=20, param2=5,
                               minRadius=minrad, maxRadius=maxrad)

    circles = np.uint16(np.around(circles))

    # for some reason, it is a 2D list, collapse it
    circles = circles[0, :]

    # circle centers are (x,y)

    print(circles)

    # toss any circles on the edge, due to noise
    edgeindices = []
    for j, i in enumerate(circles):
        if i[0] < 10 or i[1] < 10 or i[0] > 240 or i[1] > 240:
            print('on edge: ', j)
            edgeindices.append(j)

    if edgeindices:
        newcircles = np.delete(circles, edgeindices, 0)
        print(newcircles)
        circles = newcircles

    # make color image for displaying contours
    cimg = cv2.cvtColor(img8b, cv2.COLOR_GRAY2BGR)

    #  NOTE: centers are Points (x,y) so i[1],i[0]
    centers = []
    for i in circles:
        cx = i[0]
        cy = i[1]
        # draw the outer circle
        # cv2.circle(cimg, (cx, cy), i[2], (255, 255, 0), 1)
        #  draw the measured square as a circle
        cv2.circle(cimg, (cx, cy), int(10*mm2pix), (0, 255, 255), 1)
        
        # draw the center of the circle
        # cv2.circle(cimg,(cx, cy),2,(0,0,255),3)
        dprint("Center xy= ", cx, ",", cy, "Value= ", imp[cy, cx])
        dprint("Radius = ", i[2])
        centers.append((cx, cy))

    # cv2.imshow('detected circles',cimg)
    # cv2.imwrite(os.path.dirname(img) + '/cimg.png', cimg)

    numtubes = len(centers)
    dprint("Found {} tubes".format(numtubes))

    if numtubes != 9:
        print('Found {} tubes - should be 9.  Aborting.'.format(numtubes))
        return 1

    # sort the tubes in the correct order:
    #  1  2  3
    #  4  5  6
    #  7  8  9
    #  use x+4y to sort centers

    def get_key(item):
        return item[1]+4*item[0]     # remember: opencv is [y,x]

    centers = sorted(centers, key=get_key)

    for i, cxy in enumerate(centers):
        dprint("Sorted Center xy= ", cxy[0], ",", cxy[1], "Value= ", imp[cxy[1], cxy[0]])

    mean_t1s = ['T1 (ms)', 0, 0, 0, 0, 0, 0, 0, 0, 0]

    # compute mean of each tube in square of +/- 10 mm
    dx = int(10*mm2pix)
    mask = np.zeros(img8.shape, np.uint8)
    for i, cxy in enumerate(centers):
        mask[:, :] = 0                         # arrays are (y,x) !!!
        mask[cxy[1]-dx:cxy[1]+dx, cxy[0]-dx:cxy[0]+dx] = 100
        mean = cv2.mean(imp, mask=mask)
        mean_t1s[i+1] = ("%5.0f" % (mean[0]))

    if showit:
        cv2.imshow("mask", mask)

    dprint('mean_t1s = ', mean_t1s)

    # label the tubes with the mean value
    fscale = 0.4
    fthk = 1
    fnt = cv2.FONT_HERSHEY_SIMPLEX

    for i, cxy in enumerate(centers):
        #  note:  lower left corner  of text, at (cx, cy) is a cvPoint, which IS (x,y)

        tsize = cv2.getTextSize('%s' % (mean_t1s[i+1].strip()), fnt, fscale, fthk)[0]
        cx = cxy[0]-int(tsize[0]/2)
        cy = cxy[1]+int(tsize[1]/2)

        cv2.putText(cimg, "%s" % (mean_t1s[i+1].strip()), (cx, cy), fnt,
                    fscale, (255, 255, 255), fthk, cv2.LINE_AA)

    # put series number in the series description
    sernum = ''
    serdescr = ''
    if "SeriesNumber" in dset:
        sernum = 'Ser %s' % dset.SeriesNumber
    if "SeriesDescription" in dset:
        serdescr = sernum + ':' + dset.SeriesDescription
    elif "ProtocolName" in dset:
        serdescr = sernum + ':' + dset.ProtocolName

    # create unique site/date identifier
    if "wake" in dset.InstitutionName.lower():
        site = 'Wake'
    elif "VCU" in dset.InstitutionName:
        site = 'VCU'
    else:
        site = 'Null'

    sitedate = 'QA_T1MES_' + site + '_' + dset.StudyDate + '_S' + '%s' % dset.SeriesNumber + '_'

    # save image to disk
    print('Saving contours image to %s' % (os.path.dirname(img) + '/' + sitedate + 'contours.png'))
    cv2.imwrite(os.path.dirname(img) + '/' + sitedate + 'contours.png', cimg)

    if showit:
        cv2.imshow(os.path.dirname(img)+'/contours.png', cimg)

    # save info to info.csv using csv
    labels = ['Date', 'PatientName', 'Site', 'Manufacturer', 'Model', 'Version', 
              'SerDescr', 'Rows', 'Columns'] 

    info = [dset.StudyDate, dset.PatientName, dset.InstitutionName, dset.Manufacturer,
            dset.ManufacturersModelName, dset.SoftwareVersions, serdescr, dset.Rows, dset.Columns]
    with open(os.path.dirname(img) + '/' + sitedate + 'info.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(labels)
        writer.writerow(info)

    dprint('dset.PatientName = ', dset.PatientName, 'class ', dset.PatientName.__class__)
    dprint('dset.PatientID = ', dset.PatientID)
    dprint('dset.SoftwareVersions[0] = ', dset.SoftwareVersions[0])

    if dset.Manufacturer.lower().startswith('ph'):
        swversion = dset.SoftwareVersions[0]
    else:
        swversion = dset.SoftwareVersions

    # save results to results.json using json

    resultsdict = OrderedDict((('subject_id', dset.PatientName.__str__()),
                               ('t1_date', dset.StudyDate),
                               ('t1_site', dset.InstitutionName),
                               ('t1_vendor', dset.Manufacturer),
                               ('t1_model', dset.ManufacturersModelName),
                               ('t1_sw_version', swversion),
                               ('t1_serdescr', serdescr),
                               ('t1_tube1', mean_t1s[1]),
                               ('t1_tube2', mean_t1s[2]),
                               ('t1_tube3', mean_t1s[3]),
                               ('t1_tube4', mean_t1s[4]),
                               ('t1_tube5', mean_t1s[5]),
                               ('t1_tube6', mean_t1s[6]),
                               ('t1_tube7', mean_t1s[7]),
                               ('t1_tube8', mean_t1s[8]),
                               ('t1_tube9', mean_t1s[9]))
                              )

    try:
        with open(os.path.dirname(img) + '/' + sitedate + 'results.json', 'w',) as f2:
            json.dump(resultsdict, f2, indent=4, ensure_ascii=True)
    except OSError:
        print('Error: unable to save JSON output file.')

    print("Results written to contours.png, info.csv and results.json")

    # upload to redcap
    redcap_link.redcap_upload('UPBEAT_QA', os.path.dirname(img) + '/' + sitedate + 'results.json', '')

    if showit:
        print("Press any key in image window to exit.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":

    # ~~~~~~~~~~~~~~   parse command line   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    parser = argparse.ArgumentParser(
        usage="meastimes [-h] [-d 0/1] -i <phantom DCM file>",
        description="meastimes: extract T1 values in each tube in T1MES phantom image")
    parser.add_argument('-i', '--image', type=str,
                        help="axial DICOM scan of phantom",
                        default='000001.DCM')
    parser.add_argument('-d', '--debug', type=str,
                        help="turn on debugging (-d 1)",
                        default='0')
    parser.add_argument('-s', '--show', type=str,
                        help="show image of contours",
                        default='0')

    args = parser.parse_args()

    if args.debug == '1':
        DEBUGPRINT = True

    dprint('args.image = ', args.image)

    # ~~~~~~~~~~~~  call the meas_times function ~~~~~~~~~~~~~~~~~~~~~~

    if not os.path.exists(args.image):
        print("file %s not found." % args.image)
        sys.exit()
    else:
        meas_times(args.image, args.show)
