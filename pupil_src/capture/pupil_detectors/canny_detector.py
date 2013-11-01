
'''
(*)~----------------------------------------------------------------------------------
 Pupil - eye tracking platform
 Copyright (C) 2012-2013  Moritz Kassner & William Patera

 Distributed under the terms of the CC BY-NC-SA License.
 License details are in the file license.txt, distributed as part of this software.
----------------------------------------------------------------------------------~(*)
'''
# make shared modules available across pupil_src
if __name__ == '__main__':
    from sys import path as syspath
    from os import path as ospath
    loc = ospath.abspath(__file__).rsplit('pupil_src', 1)
    syspath.append(ospath.join(loc[0], 'pupil_src', 'shared_modules'))
    del syspath, ospath

import cv2
from time import sleep
import numpy as np
from methods import *
import atb
from ctypes import c_int,c_bool,c_float
from c_methods import eye_filter
from glfw import *
from gl_utils import adjust_gl_view, draw_gl_texture, clear_gl_screen, draw_gl_point_norm, draw_gl_polyline,basic_gl_setup
from template import Pupil_Detector


import logging
logger = logging.getLogger(__name__)
class Canny_Detector(Pupil_Detector):
    """a Pupil detector based on Canny_Edges"""
    def __init__(self):
        super(Canny_Detector, self).__init__()

        # coase pupil filter params
        self.coarse_filter_min = 100
        self.coarse_filter_max = 400

        # canny edge detection params
        self.blur = c_int(1)
        self.canny_thresh = c_int(200)
        self.canny_ratio= c_int(2)
        self.canny_aperture = c_int(7)

        # edge intensity filter params
        self.intensity_range = c_int(17)
        self.bin_thresh = c_int(0)

        # contour prefilter params
        self.min_contour_size = 30

        #ellipse filter params
        self.inital_ellipse_fit_threshhold = 0.5
        self.min_ratio = .3
        self.pupil_min = c_float(40.)
        self.pupil_max = c_float(200.)
        self.target_size= c_float(100.)
        self.goodness = c_float(1.)
        self.strong_perimeter_ratio_range = .8, 1.1
        self.strong_area_ratio_range = .6,1.1
        self.normal_perimeter_ratio_range = .5, 1.2
        self.normal_area_ratio_range = .4,1.2


        #ellipse history
        self.strong_evidece = []

        #debug window
        self._window = None
        self.window_should_open = False
        self.window_should_close = False

        #debug settings
        self.should_sleep = False

    def detect(self,frame,user_roi,visualize=False):
        u_r = user_roi
        if self.window_should_open:
            self.open_window()
        if self.window_should_close:
            self.close_window()

        if self._window:
            debug_img = np.zeros(frame.img.shape,frame.img.dtype)


        #get the user_roi
        img = frame.img
        r_img = img[u_r.view]
        gray_img = cv2.cvtColor(r_img,cv2.COLOR_BGR2GRAY)


        # coarse pupil detection
        integral = cv2.integral(gray_img)
        integral =  np.array(integral,dtype=c_float)
        x,y,w,response = eye_filter(integral,self.coarse_filter_min,self.coarse_filter_max)
        p_r = Roi(gray_img.shape)
        if w>0:
            p_r.set((y,x,y+w,x+w))
        else:
            p_r.set((0,0,-1,-1))
        coarse_pupil_center = x+w/2.,y+w/2.
        coarse_pupil_width = w/2.
        padding = coarse_pupil_width/4.
        pupil_img = gray_img[p_r.view]



        # binary thresholding of pupil dark areas
        hist = cv2.calcHist([pupil_img],[0],None,[256],[0,256]) #(images, channels, mask, histSize, ranges[, hist[, accumulate]])
        bins = np.arange(hist.shape[0])
        spikes = bins[hist[:,0]>40] # every intensity seen in more than 40 pixels
        if spikes.shape[0] >0:
            lowest_spike = spikes.min()
            highest_spike = spikes.max()
        else:
            lowest_spike = 200
            highest_spike = 255

        offset = self.intensity_range.value
        spectral_offset = 5
        if visualize:
            # display the histogram
            sx,sy = 100,1
            colors = ((0,0,255),(255,0,0),(255,255,0),(255,255,255))
            h,w,chan = img.shape
            hist *= 1./hist.max()  # normalize for display

            for i,h in zip(bins,hist[:,0]):
                c = colors[1]
                cv2.line(img,(w,int(i*sy)),(w-int(h*sx),int(i*sy)),c)
            cv2.line(img,(w,int(lowest_spike*sy)),(int(w-.5*sx),int(lowest_spike*sy)),colors[0])
            cv2.line(img,(w,int((lowest_spike+offset)*sy)),(int(w-.5*sx),int((lowest_spike+offset)*sy)),colors[2])
            cv2.line(img,(w,int((highest_spike)*sy)),(int(w-.5*sx),int((highest_spike)*sy)),colors[0])
            cv2.line(img,(w,int((highest_spike- spectral_offset )*sy)),(int(w-.5*sx),int((highest_spike - spectral_offset)*sy)),colors[3])

        # create dark and spectral glint masks
        self.bin_thresh.value = lowest_spike
        binary_img = bin_thresholding(pupil_img,image_upper=lowest_spike + offset)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7))
        cv2.dilate(binary_img, kernel,binary_img, iterations=2)
        spec_mask = bin_thresholding(pupil_img, image_upper=highest_spike - spectral_offset)
        cv2.erode(spec_mask, kernel,spec_mask, iterations=1)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9,9))

        #open operation to remove eye lashes
        pupil_img = cv2.morphologyEx(pupil_img, cv2.MORPH_OPEN, kernel)

        if self.blur.value >1:
            pupil_img = cv2.medianBlur(pupil_img,self.blur.value)

        edges = cv2.Canny(pupil_img,
                            self.canny_thresh.value,
                            self.canny_thresh.value*self.canny_ratio.value,
                            apertureSize= self.canny_aperture.value)


        # remove edges in areas not dark enough and where the glint is (spectral refelction from IR leds)
        edges = cv2.min(edges, spec_mask)
        edges = cv2.min(edges,binary_img)


        overlay =  img[u_r.view][p_r.view]
        if visualize:
            b,g,r = overlay[:,:,0],overlay[:,:,1],overlay[:,:,2]
            g[:] = cv2.max(g,edges)
            b[:] = cv2.max(b,binary_img)
            b[:] = cv2.min(b,spec_mask)

            # draw a frame around the automatic pupil ROI in overlay.
            overlay[::2,0] = 255 #yeay numpy broadcasting
            overlay[::2,-1]= 255
            overlay[0,::2] = 255
            overlay[-1,::2]= 255
            # draw a frame around the area we require the pupil center to be.
            overlay[padding:-padding:4,padding] = 255
            overlay[padding:-padding:4,-padding]= 255
            overlay[padding,padding:-padding:4] = 255
            overlay[-padding,padding:-padding:4]= 255

        if visualize:
            c = (100.,frame.img.shape[0]-100.)
            e1 = ((c),(self.pupil_max.value,self.pupil_max.value),0)
            e2 = ((c),(self.pupil_min.value,self.pupil_min.value),0)
            cv2.ellipse(frame.img,e1,(0,0,255),1)
            cv2.ellipse(frame.img,e2,(0,0,255),1)


        # from edges to contours
        contours, hierarchy = cv2.findContours(edges,
                                            mode=cv2.RETR_LIST,
                                            method=cv2.CHAIN_APPROX_NONE,offset=(0,0)) #TC89_KCOS
        # contours is a list containing array([[[108, 290]],[[111, 290]]], dtype=int32) shape=(number of points,1,dimension(2) )

        ### first we want to filter out the bad stuff
        # to short
        good_contours = [c for c in contours if c.shape[0]>self.min_contour_size]
        # now we learn things about each contour through looking at the curvature.
        # For this we need to simplyfy the contour so that pt to pt angles become more meaningfull
        arprox_contours = [cv2.approxPolyDP(c,epsilon=1.5,closed=False) for c in good_contours]
        if self._window:
            x_shift = coarse_pupil_width*2
            color = zip(range(0,250,15),range(0,255,15)[::-1],range(230,250))
        split_contours = []
        for c in arprox_contours:
            curvature = GetAnglesPolyline(c)
            # we split whenever there is a real kink (abs(curvature)<right angle) or a change in the genreal direction
            kink_idx = find_kink_and_dir_change(curvature,100)
            segs = split_at_corner_index(c,kink_idx)
            for s in segs:
                split_contours.append(s)
                if self._window:
                    c = color.pop(0)
                    color.append(c)
                    if s.shape[0] >2:
                        cv2.polylines(debug_img,[s],isClosed=False,color=map(lambda x: x/2,c))
                    s = s.copy()
                    s[:,:,1] +=  coarse_pupil_width*2
                    cv2.polylines(debug_img,[s],isClosed=False,color=c)
                    s[:,:,0] += x_shift
                    x_shift += 5
                    cv2.polylines(debug_img,[s],isClosed=False,color=c)

        if len(split_contours) == 0:
            # not a single usefull segment found -> no pupil found
            self.goodness.value = 100
            return {'timestamp':frame.timestamp,'norm_pupil':None}


        # removing stubs makes combinatorial search feasable
        split_contours = [c for c in split_contours if c.shape[0]>3]

        def ellipse_filter(e):
            in_center = padding < e[0][1] < pupil_img.shape[0]-padding and padding < e[0][0] < pupil_img.shape[1]-padding
            if in_center:
                center_on_dark = binary_img[e[0][1],e[0][0]]
                if center_on_dark:
                    is_round = min(e[1])/max(e[1]) >= self.min_ratio
                    if is_round:
                        right_size = self.pupil_min.value <= max(e[1]) <= self.pupil_max.value
                        if right_size:
                            return True
            return False

        def ellipse_support_ratio(e,contours):
            a,b = e[1][0]/2.,e[1][1]/2. # major minor radii of candidate ellipse
            ellipse_area =  np.pi*a*b
            ellipse_circumference = np.pi*abs(3*(a+b)-np.sqrt(10*a*b+3*(a**2+b**2)))
            actual_area = cv2.contourArea(cv2.convexHull(np.concatenate(contours)))
            actual_contour_length = sum([cv2.arcLength(c,closed=False) for c in contours])
            area_ratio = actual_area / ellipse_area
            perimeter_ratio = actual_contour_length / ellipse_circumference #we assume here that the contour lies close to the ellipse boundary
            return perimeter_ratio,area_ratio

        def final_fitting(c,edges):
            support_mask = np.zeros(edges.shape,edges.dtype)
            cv2.polylines(support_mask,c,isClosed=False,color=(255,255,255),thickness=2)
            # #draw into the suport mast with thickness 2
            new_edges = cv2.min(edges, support_mask)
            new_contours = cv2.findNonZero(new_edges)
            # if self._window:
                # debug_img[0:support_mask.shape[0],0:support_mask.shape[1],2] = new_edges
            new_e = cv2.fitEllipse(new_contours)
            return new_e,new_contours


        # finding poential candidtes for ellipses that describe the pupil
        strong_seed_ellipses = []
        normal_seed_ellipses = []
        weak_seed_ellipses = []
        for idx, c in enumerate(split_contours):
            if c.shape[0] >=5:
                e = cv2.fitEllipse(c)
                # is this ellipse a plausible canditate for a pupil
                if ellipse_filter(e):
                    distances = dist_pts_ellipse(e,c)
                    fit_variance = np.sum(distances**2)/float(distances.shape[0])
                    # if self._window:
                    #     print fit_variance
                    #     thick = min(10,fit_variance*5)
                    #     cv2.polylines(debug_img,[c],isClosed=False,color=(100,255,100),thickness=int(thick))
                    if fit_variance <= self.inital_ellipse_fit_threshhold:
                        # how much ellipse is supported by this contour?
                        perimeter_ratio,area_ratio = ellipse_support_ratio(e,[c])
                        logger.debug('Ellipse no %s with perimeter_ratio: %s , area_ratio: %s'%(idx,perimeter_ratio,area_ratio))
                        seed_ellipse = {'e':e,
                                        'base_countour_idx':[idx],
                                        'fit_variance':fit_variance }
                        if self.strong_perimeter_ratio_range[0]<= perimeter_ratio <= self.strong_perimeter_ratio_range[1] and self.strong_area_ratio_range[0]<= area_ratio <= self.strong_area_ratio_range[1]:
                            strong_seed_ellipses.append(seed_ellipse)
                            if self._window:
                                cv2.ellipse(overlay,e,(0,0,255),thickness=3)
                                self.strong_evidece.append( (u_r.add_vector(p_r.add_vector(e[0])),map(lambda x:x/5.,e[1]),e[2]) )
                                cv2.polylines(debug_img,[c],isClosed=False,color=(0,0,255),thickness=3)
                        elif self.normal_perimeter_ratio_range[0]<= perimeter_ratio <= self.normal_perimeter_ratio_range[1] and self.normal_area_ratio_range[0]<= area_ratio <= self.normal_area_ratio_range[1]:
                            normal_seed_ellipses.append(seed_ellipse)
                            if self._window and 0:
                                cv2.polylines(debug_img,[c],isClosed=False,color=(100,255,100),thickness=2)
                        else:
                            weak_seed_ellipses.append(seed_ellipse)
                            if self._window and 0:
                                cv2.polylines(debug_img,[c],isClosed=False,color=(100,255,100),thickness=1)


        # split_contours = np.array(split_contours)

        if strong_seed_ellipses:
            seed_idx = [e['base_countour_idx'][0] for e in strong_seed_ellipses]

        elif normal_seed_ellipses:
            seed_idx = [e['base_countour_idx'][0] for e in normal_seed_ellipses]

        elif weak_seed_ellipses:
            seed_idx = [e['base_countour_idx'][0] for e in weak_seed_ellipses]

        if not (strong_seed_ellipses or weak_seed_ellipses or normal_seed_ellipses):
            if self._window:
                self.gl_display_in_window(debug_img)
            self.goodness.value = 100
            return {'timestamp':frame.timestamp,'norm_pupil':None}

        if self._window:
            cv2.polylines(debug_img,[split_contours[i] for i in seed_idx],isClosed=False,color=(255,255,100),thickness=3)

        def ellipse_eval(contours):
            c = np.concatenate(contours)
            e = cv2.fitEllipse(c)
            d = dist_pts_ellipse(e,c)
            fit_variance = np.sum(d**2)/float(d.shape[0])
            return fit_variance <= self.inital_ellipse_fit_threshhold


        solutions = pruning_quick_combine(split_contours,ellipse_eval,seed_idx)
        sc = np.array(split_contours)
        if self._window:
            ratings = []
            for s in solutions:
                e = cv2.fitEllipse(np.concatenate(sc[s]))
                perimeter_ratio,area_ratio = ellipse_support_ratio(e,sc[s])
                distances = dist_pts_ellipse(e,np.concatenate(sc[s]))
                fit_variance = np.sum(distances**2)/float(distances.shape[0])
                ratings.append(-fit_variance)
                # print perimeter_ratio,area_ratio,fit_variance

                if area_ratio > .5 and perimeter_ratio > .5 and fit_variance < .3 or 1:
                    cv2.ellipse(debug_img,e,(0,0,255))
                    cv2.polylines(debug_img,sc[s],isClosed=False,color=(255,0,0),thickness=1)
            best_solutions = [x for (y,x) in sorted(zip(ratings,solutions))]
            for s in best_solutions[:3]:
                e = cv2.fitEllipse(np.concatenate(sc[s]))
                cv2.ellipse(overlay,e,(0,0,255))

        # if self._window:
        #     for e in self.strong_evidece:
        #         cv2.ellipse(frame.img,e,(0,255,0))



        for seed in strong_seed_ellipses:
            pass
        for seed in normal_seed_ellipses:
            pass
        for seed in weak_seed_ellipses:
            pass


        # if we get here - no ellipse was found :-(
        if self._window:
            self.gl_display_in_window(debug_img)
        self.goodness.value = 100
        return {'timestamp':frame.timestamp,'norm_pupil':None}



    # Display and interface methods


    def create_atb_bar(self,pos):
        self._bar = atb.Bar(name = "Canny_Pupil_Detector", label="Pupil_Detector",
            help="pupil detection parameters", color=(50, 50, 50), alpha=100,
            text='light', position=pos,refresh=.3, size=(200, 100))
        self._bar.add_button("open debug window", self.toggle_window)
        self._bar.add_var("pupil_intensity_range",self.intensity_range)
        self._bar.add_var("pupil_min",self.pupil_min)
        self._bar.add_var("Pupil_Aparent_Size",self.target_size)
        self._bar.add_var("pupil_max",self.pupil_max)

        self._bar.add_var("Pupil_Shade",self.bin_thresh, readonly=True)
        self._bar.add_var("Pupil_Certainty",self.goodness, readonly=True)
        self._bar.add_var("Image_Blur",self.blur, step=2,min=1,max=9)
        # self._bar.add_var("Canny_aparture",self.canny_aperture, step=2,min=3,max=7)
        # self._bar.add_var("canny_threshold",self.canny_thresh, step=1,min=0)
        # self._bar.add_var("Canny_ratio",self.canny_ratio, step=1,min=1)

    def toggle_window(self):
        if self._window:
            self.window_should_close = True
        else:
            self.window_should_open = True

    def open_window(self):
        if not self._window:
            if 0: #we are not fullscreening
                monitor = self.monitor_handles[self.monitor_idx.value]
                mode = glfwGetVideoMode(monitor)
                height,width= mode[0],mode[1]
            else:
                monitor = None
                height,width= 640,360

            active_window = glfwGetCurrentContext()
            self._window = glfwCreateWindow(height, width, "Plugin Window", monitor=monitor, share=None)
            if not 0:
                glfwSetWindowPos(self._window,200,0)

            self.on_resize(self._window,height,width)

            #Register callbacks
            glfwSetWindowSizeCallback(self._window,self.on_resize)
            # glfwSetKeyCallback(self._window,self.on_key)
            glfwSetWindowCloseCallback(self._window,self.on_close)

            # gl_state settings
            glfwMakeContextCurrent(self._window)
            basic_gl_setup()
            glfwMakeContextCurrent(active_window)

            self.window_should_open = False

    # window calbacks
    def on_resize(self,window,w, h):
        active_window = glfwGetCurrentContext()
        glfwMakeContextCurrent(window)
        adjust_gl_view(w,h)
        glfwMakeContextCurrent(active_window)

    def on_close(self,window):
        self.window_should_close = True

    def close_window(self):
        if self._window:
            glfwDestroyWindow(self._window)
            self._window = None
            self.window_should_close = False


    def gl_display_in_window(self,img):
        active_window = glfwGetCurrentContext()
        glfwMakeContextCurrent(self._window)
        clear_gl_screen()
        # gl stuff that will show on your plugin window goes here
        draw_gl_texture(img,interpolation=False)
        glfwSwapBuffers(self._window)
        glfwMakeContextCurrent(active_window)

