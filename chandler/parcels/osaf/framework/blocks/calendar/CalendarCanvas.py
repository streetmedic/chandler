""" Canvas for calendaring blocks
"""

__version__ = "$Revision$"
__date__ = "$Date$"
__copyright__ = "Copyright (c) 2004 Open Source Applications Foundation"
__license__ = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

import wx
import mx.DateTime as DateTime

import osaf.contentmodel.calendar.Calendar as Calendar

import osaf.framework.blocks.DragAndDrop as DragAndDrop
import osaf.framework.blocks.Block as Block
import osaf.framework.blocks.calendar.CollectionCanvas as CollectionCanvas

class ColumnarCanvasItem(CollectionCanvas.CanvasItem):
    def __init__(self, *arguments, **keywords):
        super(ColumnarCanvasItem, self).__init__(*arguments, **keywords)
        
        self._resizeLowBounds = wx.Rect(self.bounds.x,
                                        self.bounds.y + self.bounds.height - 5,
                                        self.bounds.width, 5)
        
        self._resizeTopBounds = wx.Rect(self.bounds.x, self.bounds.y,
                                        self.bounds.width, 5)

    def isHitResize(self, point):
        """ Hit testing of a resize region.
        
        @param point: point in unscrolled coordinates
        @type point: wx.Point
        @return: True if the point hit the resize region
        @rtype: Boolean
        """
        return (self._resizeTopBounds.Inside(point) or
                self._resizeLowBounds.Inside(point))

    def getResizeMode(self, point):
        """ Returns the mode of the resize, either 'TOP' or 'LOW'.

        The resize mode is 'TOP' if dragging from the top of the event,
        and 'LOW' if dragging from the bottom of the event. None indicates
        that we are not resizing at all.

        @param point: drag start position in uscrolled coordinates
        @type point: wx.Point
        @return: resize mode, 'TOP', 'LOW' or None
        @rtype: string or None
        """
        
        if self._resizeTopBounds.Inside(point):
            return "TOP"
        if self._resizeLowBounds.Inside(point):
            return "LOW"
        return None


class CalendarEventHandler(object):

    """ Mixin to a widget class """

    def OnPrev(self, event):
        self.blockItem.decrementRange()
        self.blockItem.postDateChanged()
        self.wxSynchronizeWidget()

    def OnNext(self, event):
        self.blockItem.incrementRange()
        self.blockItem.postDateChanged()
        self.wxSynchronizeWidget()

    def OnToday(self, event):
        today = DateTime.today()
        self.blockItem.setRange(today)
        self.blockItem.postDateChanged()
        self.wxSynchronizeWidget()

class CalendarBlock(CollectionCanvas.CollectionBlock):
    """ Abstract block used as base Kind for Calendar related blocks.

    This base class can be used for any block that displays a collection of
    items based on a date range.

    @ivar rangeStart: beginning of the currently displayed range (persistent)
    @type rangeStart: mx.DateTime.DateTime
    @ivar rangeIncrement: increment used to find the next or prev block of time
    @type rangeIncrement: mx.DateTime.RelativeDateTime
    """
    
    def __init__(self, *arguments, **keywords):
        super(CalendarBlock, self).__init__(*arguments, **keywords)

    # Event handling
    
    def onSelectedDateChangedEvent(self, event):
        """
        Sets the selected date range and synchronizes the widget.

        @param event: event sent on selected date changed event
        @type event: osaf.framework.blocks.Block.BlockEvent
        @param event['start']: start of the newly selected date range
        @type event['start']: mx.DateTime.DateTime
        """
        self.setRange(event.arguments['start'])
        self.widget.wxSynchronizeWidget()

    def postDateChanged(self):
        """
        Convenience method for changing the selected date.
        """
        self.postEventByName ('SelectedDateChanged',{'start':self.selectedDate})

    # Managing the date range

    def setRange(self, date):
        """ Sets the range to include the given date.

        @param date: date to include
        @type date: mx.DateTime.DateTime
        """
        self.rangeStart = date
        self.selectedDate = self.rangeStart

    def isDateInRange(self, date):
        """ Does the given date currently appear on the calendar block?

        @type date: mx.DateTime.DateTime
        @return: True if the given date appears on the calendar
        @rtype: Boolean
        """
        begin = self.rangeStart
        end = begin + self.rangeIncrement
        return ((date >= begin) and (date < end))

    def incrementRange(self):
        """ Increments the calendar's current range """
        self.rangeStart += self.rangeIncrement
        if self.selectedDate:
            self.selectedDate += self.rangeIncrement

    def decrementRange(self):
        """ Decrements the calendar's current range """
        self.rangeStart -= self.rangeIncrement
        if self.selectedDate:
            self.selectedDate -= self.rangeIncrement

    # Get items from the collection

    def getDayItemsByDate(self, date):
        items = []
        nextDate = date + DateTime.RelativeDateTime(days=1)
        for item in self.contents:
            try:
                anyTime = item.anyTime
            except AttributeError:
                anyTime = False
            try:
                allDay = item.allDay
            except AttributeError:
                allDay = False
            if (item.hasLocalAttributeValue('startTime') and
                (allDay or anyTime) and
                (item.startTime >= date) and
                (item.startTime < nextDate)):
                items.append(item)
        return items

    def getItemsByDate(self, date):
        """
        Convenience method to look for the items in the block's contents
        that appear on the given date. @@@ We may push this work down into
        ItemCollections and/or Queries.

        @type date: mx.DateTime.DateTime
        @return: the items in this collection that appear on the given date
        @rtype: list of Items
        """
        # make this a generator?
        items = []
        nextDate = date + DateTime.RelativeDateTime(days=1)
        for item in self.contents:
            try:
                anyTime = item.anyTime
            except AttributeError:
                anyTime = False
            try:
                allDay = item.allDay
            except AttributeError:
                allDay = False
            if (item.hasLocalAttributeValue('startTime') and
                item.hasLocalAttributeValue('endTime') and
                (not allDay and not anyTime) and
                (item.startTime >= date) and
                (item.startTime < nextDate)):
                items.append(item)
        return items

class wxWeekPanel(wx.Panel, CalendarEventHandler):
    def __init__(self, *arguments, **keywords):
        super (wxWeekPanel, self).__init__ (*arguments, **keywords)

        self.Bind(wx.EVT_ERASE_BACKGROUND, self.OnEraseBackground)

        self.headerCanvas = wxWeekHeaderCanvas(self, -1)
        self.columnCanvas = wxWeekColumnCanvas(self, -1)
        self.headerCanvas.parent = self
        self.columnCanvas.parent = self

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(self.headerCanvas, 0, wx.EXPAND)
        box.Add(self.columnCanvas, 1, wx.EXPAND)
        self.SetSizer(box)

    def OnEraseBackground(self, event):
        pass

    def OnInit(self):
        self.headerCanvas.OnInit()
        self.columnCanvas.OnInit()

    def wxSynchronizeWidget(self):
        self.Layout()
        self.headerCanvas.wxSynchronizeWidget()
        self.columnCanvas.wxSynchronizeWidget()
        
    def PrintCanvas(self, dc):
        self.columnCanvas.PrintCanvas(dc)

    def OnDaySelect(self, event):
        # pick the date based on the index
        index = event.GetEventObject().index
        startDate = self.blockItem.rangeStart
        selectedDate = startDate + DateTime.RelativeDateTime(days=index)
        
        # @@@ add method on block item for setting selected date
        self.blockItem.selectedDate = selectedDate
        self.blockItem.dayMode = True
        self.blockItem.postDateChanged()
        self.wxSynchronizeWidget()

    def OnWeekSelect(self, event):
        self.blockItem.dayMode = False
        self.blockItem.selectedDate = self.blockItem.rangeStart
        self.blockItem.postDateChanged()
        self.wxSynchronizeWidget()

    def OnExpand(self, event):
        self.headerCanvas.toggleSize()
        self.wxSynchronizeWidget()

class wxWeekHeaderCanvas(CollectionCanvas.wxCollectionCanvas):
    def __init__(self, *arguments, **keywords):
        super (wxWeekHeaderCanvas, self).__init__ (*arguments, **keywords)

        self.SetMinSize((-1, 106))
        self.fixed = True

        # @@@ constants
        self.yOffset = 50
        self.hourHeight = 40
        self.weekHeaderHeight = 22
        self.scrollbarWidth = wx.SystemSettings_GetMetric(wx.SYS_VSCROLL_X)

    def OnInit(self):
        self.editor = wxInPlaceEditor(self, -1)

        # Setup the navigation buttons
        today = DateTime.today()
        
        self.prevButton = CollectionCanvas.CanvasBitmapButton(self, "application/images/backarrow.png")
        self.nextButton = CollectionCanvas.CanvasBitmapButton(self, "application/images/forwardarrow.png")
        self.todayButton = CollectionCanvas.CanvasTextButton(self, today.Format("%b %d, %Y"),
                                                             self.bigFont, self.bigFontColor,
                                                             self.bgColor)
        self.monthButton = CollectionCanvas.CanvasTextButton(self, today.Format("%B %Y"),
                                                             self.bigFont, self.bigFontColor,
                                                             self.bgColor)
                                                             
        self.prevButton.UpdateSize()
        self.nextButton.UpdateSize()
 
        self.Bind(wx.EVT_BUTTON, self.parent.OnPrev, self.prevButton)
        self.Bind(wx.EVT_BUTTON, self.parent.OnNext, self.nextButton)
        self.Bind(wx.EVT_BUTTON, self.parent.OnToday, self.todayButton)
        self.Bind(wx.EVT_SIZE, self.OnSize)

        # Setup the weekday header buttons
        self.weekButton = CollectionCanvas.CanvasTextButton(self, "Week",
                                                            self.bigFont,
                                                            self.bigFontColor,
                                                            self.bgColor)
        self.Bind(wx.EVT_BUTTON, self.parent.OnWeekSelect, self.weekButton)
        
        self.dayButtons = []
        for day in range(7):
            button = CollectionCanvas.CanvasTextButton(self, " ",
                                                       self.bigFont,
                                                       self.bigFontColor,
                                                       self.bgColor)
            button.index = day
            self.dayButtons.append(button)
            self.Bind(wx.EVT_BUTTON, self.parent.OnDaySelect, button)

        self.expandButton = CollectionCanvas.CanvasTextButton(self, "+",
                                                              self.bigFont,
                                                              self.bigFontColor,
                                                              self.bgColor)
        self.Bind(wx.EVT_BUTTON, self.parent.OnExpand, self.expandButton)

    def OnSize(self, event):
        self._doDrawingCalculations()

        # size navigation buttons
        monthButtonSize = self.monthButton.GetSize()
        xMonth = (self.size.width - monthButtonSize.width)/2
        self.monthButton.Move((xMonth, 5))

        nextButtonSize = self.nextButton.GetSize()
        prevButtonSize = self.prevButton.GetSize()        
        todayButtonSize = self.todayButton.GetSize()

        self.nextButton.Move((self.size.width - nextButtonSize.width - 5, 5))
        self.prevButton.Move((self.size.width - nextButtonSize.width - prevButtonSize.width - 10, 5))
        self.todayButton.Move((self.size.width - nextButtonSize.width - prevButtonSize.width - todayButtonSize.width - 15, 5))

        # size weekday header buttons
        self.weekButton.SetDimensions(0, self.yOffset - self.weekHeaderHeight,
                                      self.xOffset, self.weekHeaderHeight)
        for day in range(6):
            self.dayButtons[day].SetDimensions(self.xOffset + (self.dayWidth * day),
                                               self.yOffset - self.weekHeaderHeight,
                                               self.dayWidth, self.weekHeaderHeight)

        lastWidth = self.size.width - self.scrollbarWidth - (self.dayWidth * 6) - self.xOffset
        self.dayButtons[6].SetDimensions(self.xOffset + (self.dayWidth * 6), 
                                         self.yOffset - self.weekHeaderHeight,
                                         lastWidth, self.weekHeaderHeight)
        self.expandButton.SetDimensions(self.size.width - self.scrollbarWidth,
                                        self.yOffset - self.weekHeaderHeight, 
                                        self.scrollbarWidth, self.weekHeaderHeight)    

        self.Refresh()
        event.Skip()

    def wxSynchronizeWidget(self):

        selectedDate = self.parent.blockItem.selectedDate
        startDate = self.parent.blockItem.rangeStart
        
        self.monthButton.SetLabel(selectedDate.Format("%B %Y"))
        self.monthButton.UpdateSize()
        self.todayButton.UpdateSize()

        for day in range(7):
            currentDate = startDate + DateTime.RelativeDateTime(days=day)
            dayName = currentDate.Format('%a ') + str(currentDate.day)

            self.dayButtons[day].SetLabel(dayName)
            
        self.Layout()
        self.Refresh()

    def toggleSize(self):
        # Toggles size between fixed and large enough to show all tasks
        if self.fixed:
            if self.fullHeight > 106:
                self.SetMinSize((-1, self.fullHeight + 9))
            else:
                self.SetMinSize((-1, 106))
        else:
            self.SetMinSize((-1, 106))
        self.fixed = not self.fixed

    # Drawing code

    def _doDrawingCalculations(self):
        self.size = self.GetVirtualSize()
        
        self.xOffset = (self.size.width - self.scrollbarWidth) / 8
        self.dayWidth = (self.size.width - self.scrollbarWidth - self.xOffset) / self.parent.blockItem.daysPerView
        self.dayHeight = self.hourHeight * 24
        if self.parent.blockItem.dayMode:
            self.parent.columns = 1
        else:
            self.parent.columns = self.parent.blockItem.daysPerView

    def DrawBackground(self, dc):
        self._doDrawingCalculations()

        # Use the transparent pen for painting the background
        dc.SetPen(wx.TRANSPARENT_PEN)
        
        # Paint the entire background
        dc.SetBrush(wx.WHITE_BRUSH)
        dc.DrawRectangle(0, 0, self.size.width, self.size.height)

        dc.SetPen(wx.Pen(wx.Colour(204, 204, 204)))

        # Draw lines between days
        for day in range(self.parent.columns):
            dc.DrawLine(self.xOffset + (self.dayWidth * day),
                        self.yOffset,
                        self.xOffset + (self.dayWidth * day),
                        self.size.height)

        # Draw one extra line to parallel the scrollbar below
        dc.DrawLine(self.size.width - self.scrollbarWidth,
                    self.yOffset - self.weekHeaderHeight,
                    self.size.width - self.scrollbarWidth,
                    self.size.height)


        # Draw the boxes for the weekdays
        # @@@ we shouldn't have to do this, the header should do this for us

        # Draw the top and bottom lines for the boxes
        dc.DrawLine(0, self.yOffset - self.weekHeaderHeight,
                    self.xOffset + self.size.width,
                    self.yOffset - self.weekHeaderHeight)
        dc.DrawLine(0, self.yOffset,
                    self.xOffset + self.size.width,
                    self.yOffset)

        # Draw the lines between the boxes
        for day in range(self.parent.blockItem.daysPerView):
            dc.DrawLine(self.xOffset + (self.dayWidth * day),
                        self.yOffset - self.weekHeaderHeight,
                        self.xOffset + (self.dayWidth * day),
                        self.yOffset)

        # Draw the selected day (or show week mode selected)
        # @@@ hack hack -- unfortunately, the header/button can't
        # handle this for us, we need to do it while drawing
        # the background. Eventually the header should do this
        # for us.
        
        startDay = self.parent.blockItem.rangeStart
        dc.SetPen(wx.Pen(wx.BLUE))

        if self.parent.blockItem.dayMode == True:
            selectedDay = self.parent.blockItem.selectedDate
            delta = selectedDay - startDay

            if delta.day == 6:
                dc.DrawRectangle(self.xOffset + (self.dayWidth * 6),
                                 self.yOffset - self.weekHeaderHeight + 1,
                                 self.size.width - self.scrollbarWidth - (self.dayWidth * 6) - self.xOffset,
                                 self.weekHeaderHeight - 1)
                                 
            else:
                dc.DrawRectangle(self.xOffset + (self.dayWidth * delta.day) + 1,
                                 self.yOffset - self.weekHeaderHeight + 1,
                                 self.dayWidth - 1,
                                 self.weekHeaderHeight - 1)
        else:
            dc.DrawRectangle(1, self.yOffset - self.weekHeaderHeight + 1,
                             self.xOffset - 1,
                             self.weekHeaderHeight - 1)


    def DrawCells(self, dc):
        self._doDrawingCalculations()
        self.canvasItemList = []

        if self.parent.blockItem.dayMode:
            startDay = self.parent.blockItem.selectedDate
            width = self.size.width
        else:
            startDay = self.parent.blockItem.rangeStart
            width = self.dayWidth

        self.fullHeight = 0
        for day in range(self.parent.columns):
            currentDate = startDay + DateTime.RelativeDateTime(days=day)
            rect = wx.Rect((self.dayWidth * day) + self.xOffset, self.yOffset,
                           width, self.size.height)
            self.DrawDay(dc, currentDate, rect)

        # Draw a line across the bottom of the header
        dc.SetPen(wx.Pen(wx.Colour(204, 204, 204)))
        dc.DrawLine(0, self.size.height - 1,
                    self.size.width, self.size.height - 1)
        dc.DrawLine(0, self.size.height - 4,
                    self.size.width, self.size.height - 4)
        dc.SetPen(wx.Pen(wx.Colour(229, 229, 229)))
        dc.DrawLine(0, self.size.height - 2,
                    self.size.width, self.size.height - 2)
        dc.DrawLine(0, self.size.height - 3,
                    self.size.width, self.size.height - 3)



    def DrawDay(self, dc, date, rect):
        dc.SetTextForeground(wx.BLACK)
        dc.SetFont(self.smallFont)

        x = rect.x
        y = rect.y
        w = rect.width
        h = 15

        for item in self.parent.blockItem.getDayItemsByDate(date):
            itemRect = wx.Rect(x, y, w, h)
            
            canvasItem = CollectionCanvas.CanvasItem(itemRect, item)
            self.canvasItemList.append(canvasItem)
            
            # keep track of the current drag/resize box
            if self._currentDragBox and self._currentDragBox.item == item:
                self._currentDragBox = canvasItem

            if (self.parent.blockItem.selection is item):
                dc.SetBrush(wx.Brush(wx.Colour(217, 217, 217)))
                dc.SetPen(wx.Pen(wx.Colour(102, 102, 102)))
                dc.DrawRectangleRect(itemRect)

            if (item.transparency == "confirmed"):
                pen = wx.Pen(wx.BLACK, 3)
            elif (item.transparency == "fyi"):
                pen = wx.Pen(wx.LIGHT_GREY, 3)
            elif (item.transparency == "tentative"):
                pen = wx.Pen(wx.BLACK, 3, wx.DOT)

            pen.SetCap(wx.CAP_BUTT)
            dc.SetPen(pen)
            dc.DrawLine(itemRect.x + 2, itemRect.y + 3,
                        itemRect.x + 2, itemRect.y + itemRect.height - 3)

            # Shift text
            itemRect.x = itemRect.x + 6
            itemRect.width = itemRect.width - 6
            self.DrawWrappedText(dc, item.displayName, itemRect)

            y += h
            
        if (y > self.fullHeight):
            self.fullHeight = y

    def OnSelectItem(self, item):
        self.parent.blockItem.selection = item
        self.parent.blockItem.postSelectItemBroadcast()
        self.parent.wxSynchronizeWidget()

    def OnCreateItem(self, unscrolledPosition, createOnDrag):
        if not createOnDrag:
            view = self.parent.blockItem.itsView
            newTime = self.getDateTimeFromPosition(unscrolledPosition)
            event = Calendar.CalendarEvent(view=view)
            event.InitOutgoingAttributes()
            event.ChangeStart(DateTime.DateTime(newTime.year, newTime.month,
                                                newTime.day,
                                                event.startTime.hour,
                                                event.startTime.minute))
            event.allDay = True
            self.OnSelectItem(event)
            view.commit()
        return None

    def OnDraggingItem(self, unscrolledPosition):
        if self.parent.blockItem.dayMode:
            return
        
        newTime = self.getDateTimeFromPosition(unscrolledPosition)
        item = self._currentDragBox.getItem()
        if (newTime.absdate != item.startTime.absdate):
            item.ChangeStart(DateTime.DateTime(newTime.year, newTime.month,
                                               newTime.day,
                                               item.startTime.hour,
                                               item.startTime.minute))
            self.Refresh()

    def GrabFocusHack(self):
        self.editor.SaveItem()
        self.editor.Hide()

    def OnEditItem(self, box):
        position = box.bounds.GetPosition()
        size = box.bounds.GetSize()

        self.editor.SetItem(box.getItem(), position, size, size.height)

    def getDateTimeFromPosition(self, position):
        # bound the position by the available space that the user 
        # can see/scroll to
        yPosition = max(position.y, 0)
        xPosition = max(position.x, self.xOffset)
        
        if (self.fixed):
            height = self.GetMinSize().GetWidth()
        else:
            height = self.fullHeight
            
        yPosition = min(yPosition, height)
        xPosition = min(xPosition, self.xOffset + self.dayWidth * self.parent.columns - 1)

        if self.parent.blockItem.dayMode:
            newDay = self.parent.blockItem.selectedDate
        elif self.dayWidth > 0:
            deltaDays = (xPosition - self.xOffset) / self.dayWidth
            startDay = self.parent.blockItem.rangeStart
            newDay = startDay + DateTime.RelativeDateTime(days=deltaDays)
        else:
            newDay = self.parent.blockItem.rangeStart
        return newDay

class wxWeekColumnCanvas(CollectionCanvas.wxCollectionCanvas):
    def __init__(self, *arguments, **keywords):
        super (wxWeekColumnCanvas, self).__init__ (*arguments, **keywords)

        self.Bind(wx.EVT_SCROLLWIN, self.OnScroll)

    def OnScroll(self, event):
        self.Refresh()
        event.Skip()

    def wxSynchronizeWidget(self):
        self.Refresh()

    def OnInit(self):
        self.editor = wxInPlaceEditor(self, -1) 
        
        # @@@ rationalize drawing calculations...
        self._scrollYRate = 10
        self.SetVirtualSize((self.GetVirtualSize().width, 40*24))
        self.SetScrollRate(0, self._scrollYRate)
        self.Scroll(0, (40*7)/self._scrollYRate)

    def ScaledScroll(self, scrollX, scrollY, buffer=0):
        self.Scroll(scrollX, (scrollY / self._scrollYRate) + buffer)
        
    def _doDrawingCalculations(self):
        # @@@ magic numbers
        self.size = self.GetVirtualSize()
        self.xOffset = self.size.width / 8
        self.hourHeight = 40
        if self.parent.blockItem.dayMode:
            self.parent.columns = 1
        else:
            self.parent.columns = self.parent.blockItem.daysPerView

        self.dayWidth = (self.size.width - self.xOffset) / self.parent.columns
            
        self.dayHeight = self.hourHeight * 24

    def DrawBackground(self, dc):
        self._doDrawingCalculations()

        # Use the transparent pen for painting the background
        dc.SetPen(wx.TRANSPARENT_PEN)
        
        # Paint the entire background
        dc.SetBrush(wx.WHITE_BRUSH)
        dc.DrawRectangle(0, 0, self.size.width, self.size.height + 10)

        # Set text properties for legend
        dc.SetTextForeground(wx.Colour(153, 153, 153))
        dc.SetFont(self.bigBoldFont)

        # Use topTime to draw am/pm on the topmost hour
        topCoordinate = self.CalcUnscrolledPosition((0,0))
        topTime = self.getDateTimeFromPosition(wx.Point(topCoordinate[0],
                                                        topCoordinate[1]))

        # Draw the lines separating hours
        for hour in range(24):
            
            # Draw the hour legend
            if (hour > 0):
                if (hour == 1):
                    hourString = "am 1"
                elif (hour == 12): 
                    hourString = "pm 12"
                elif (hour > 12):
                    if (hour == (topTime.hour + 1)): # topmost hour
                        hourString = "pm %s" % str(hour - 12)
                    else:
                        hourString = str(hour - 12)
                else:
                    if (hour == (topTime.hour + 1)): # topmost hour
                        hourString = "am %s" % str(hour)
                    else:
                        hourString = str(hour)
                wText, hText = dc.GetTextExtent(hourString)
                dc.DrawText(hourString,
                            self.xOffset - wText - 5,
                             hour * self.hourHeight - (hText/2))
            
            # Draw the line between hours
            dc.SetPen(wx.Pen(wx.Colour(204, 204, 204)))
            dc.DrawLine(self.xOffset,
                         hour * self.hourHeight,
                        self.size.width,
                         hour * self.hourHeight)

            # Draw the line between half hours
            dc.SetPen(wx.Pen(wx.Colour(229, 229, 229)))
            dc.DrawLine(self.xOffset,
                         hour * self.hourHeight + (self.hourHeight/2),
                        self.size.width,
                         hour * self.hourHeight + (self.hourHeight/2))

        # Draw lines between days
        for day in range(self.parent.columns):
            if day == 0:
                dc.SetPen(wx.Pen(wx.Colour(204, 204, 204)))
            else:
                dc.SetPen(wx.Pen(wx.Colour(229, 229, 229)))
            dc.DrawLine(self.xOffset + (self.dayWidth * day), 0,
                        self.xOffset + (self.dayWidth * day), self.size.height)

    def DrawCells(self, dc):
        self._doDrawingCalculations()
        self.canvasItemList = []

        if self.parent.blockItem.dayMode:
            startDay = self.parent.blockItem.selectedDate
        else:
            startDay = self.parent.blockItem.rangeStart
        
        for day in range(self.parent.columns):
            currentDate = startDay + DateTime.RelativeDateTime(days=day)
            rect = wx.Rect((self.dayWidth * day) + self.xOffset, 0,
                           self.dayWidth, self.size.height)
            self.DrawDay(dc, currentDate, rect)
                         

    def DrawDay(self, dc, date, rect):
        # Scaffolding, we'll get more sophisticated here

        # Set up fonts and brushes for drawing the events
        dc.SetTextForeground(wx.BLACK)
        dc.SetBrush(wx.WHITE_BRUSH)

        selectedBox = None
        # Draw the events
        for item in self.parent.blockItem.getItemsByDate(date):
            time = item.startTime
            itemRect = wx.Rect(rect.x,
                               rect.y + int(self.hourHeight * (time.hour + time.minute/float(60))),
                               rect.width,
                               int(item.duration.hours * self.hourHeight))

            canvasItem = ColumnarCanvasItem(itemRect, item)
            self.canvasItemList.append(canvasItem)

            # keep track of the current drag/resize box
            if self._currentDragBox and self._currentDragBox.item == item:
                self._currentDragBox = canvasItem                
                
            # save the selected box to be drawn last
            if self.parent.blockItem.selection is item:
                selectedBox = canvasItem
            else:
                self.DrawCanvasItem(canvasItem, dc)
            
        # now draw the current item on top of everything else
        if selectedBox:
            dc.SetBrush(wx.Brush(wx.Colour(229, 229, 229)))
            self.DrawCanvasItem(selectedBox, dc)
            
    def DrawCanvasItem(self, canvasItem, dc):
        item = canvasItem.item
        itemRect = canvasItem.bounds
        time = item.startTime

        # Draw one event
        headline = time.Format('%I:%M %p ') + item.displayName

        dc.SetPen(wx.Pen(wx.Colour(153, 153, 153)))
        dc.DrawRoundedRectangleRect(itemRect, radius=10)

        if (item.transparency == "confirmed"):
            pen = wx.Pen(wx.BLACK, 3)
        elif (item.transparency == "fyi"):
            pen = wx.Pen(wx.LIGHT_GREY, 3)
        elif (item.transparency == "tentative"):
            pen = wx.Pen(wx.BLACK, 3, wx.DOT)

        pen.SetCap(wx.CAP_BUTT)
        dc.SetPen(pen)
        dc.DrawLine(itemRect.x + 2, itemRect.y + 7,
                    itemRect.x + 2, itemRect.y + itemRect.height - 7)

        # Shift text
        timeString = time.Format('%I:%M %p').lower()

        timeRect = wx.Rect(itemRect.x + 3 + 5,
                           itemRect.y + 3,
                           itemRect.width - (3 + 10),
                           15)
        
        dc.SetFont(self.smallBoldFont)
        y = self.DrawWrappedText(dc, timeString, timeRect)
        
        textRect = wx.Rect(itemRect.x + 3 + 5, y,
                           itemRect.width - (3 + 10),
                           itemRect.height - (y - itemRect.y))

        dc.SetFont(self.smallFont)
        self.DrawWrappedText(dc, item.displayName, textRect)


    # handle mouse related actions: move, resize, create, select

    def GrabFocusHack(self):
        self.editor.SaveItem()
        self.editor.Hide()

    def OnEditItem(self, box):
        position = self.CalcScrolledPosition(box.bounds.GetPosition())
        size = box.bounds.GetSize()

        textPos = wx.Point(position.x + 8, position.y + 15)
        textSize = wx.Size(size.width - 13, size.height - 20)

        self.editor.SetItem(box.getItem(), textPos, textSize, self.smallFont.GetPointSize()) 

    def OnSelectItem(self, item):
        self.parent.blockItem.selection = item
        self.parent.blockItem.postSelectItemBroadcast()
        self.parent.wxSynchronizeWidget()

    def OnCreateItem(self, unscrolledPosition, createOnDrag):
        if createOnDrag:
            # @@@ disable until we work out repository issues
            # event.duration = DateTime.DateTimeDelta(0, 0, 60)
            #     x, y = self.getPositionFromDateTime(newTime)
            #     eventRect = wx.Rect(x, y,
            #          self.dayWidth - 1,
            #          int(event.duration.hours * self.hourHeight) - 1)
            pass
        else:
            # @@@ this code might want to live somewhere else, refactored
            view = self.parent.blockItem.itsView
            newTime = self.getDateTimeFromPosition(unscrolledPosition)
            event = Calendar.CalendarEvent(view=view)
            event.InitOutgoingAttributes()
            event.ChangeStart(newTime)
            self.OnSelectItem(event)

            # @@@ Bug#1854 currently this is too slow,
            # and the event causes flicker
            view.commit()
        return None
    
    def OnResizingItem(self, unscrolledPosition):
        newTime = self.getDateTimeFromPosition(unscrolledPosition)
        item = self._currentDragBox.getItem()
        resizeMode = self.GetResizeMode()
        delta = DateTime.DateTimeDelta(0, 0, 15)
        
        # make sure we're changing by at least delta, and 
        # staying on the same day (we don't support resizing across days yet)
        if (resizeMode == "LOW" and 
            newTime > (item.startTime + delta) and
            item.startTime.day == newTime.day):
            item.endTime = newTime
        elif (resizeMode == "TOP" and 
              newTime < (item.endTime - delta) and
              item.endTime.day == newTime.day):
            item.startTime = newTime
        self.Refresh()
    
    def OnDraggingItem(self, unscrolledPosition):
        # at the start of the drag, the mouse was somewhere inside the
        # dragbox, but not necessarily exactly at x,y
        #
        # so account for the original offset within the ORIGINAL dragbox so the 
        # mouse cursor stays in the same place relative to the original box
        dy = (self._dragStartUnscrolled.y - self._originalDragBox.bounds.y)
        position = wx.Point(unscrolledPosition.x, unscrolledPosition.y - dy)
        
        newTime = self.getDateTimeFromPosition(position)
        item = self._currentDragBox.getItem()
        if ((newTime.absdate != item.startTime.absdate) or
            (newTime.hour != item.startTime.hour) or
            (newTime.minute != item.startTime.minute)):
            item.ChangeStart(newTime)
            self.Refresh()

    def getDateTimeFromPosition(self, position):
        # bound the position by the available space that the user 
        # can see/scroll to
        yPosition = max(position.y, 0)
        xPosition = max(position.x, self.xOffset)
        
        yPosition = min(yPosition, self.hourHeight * 24 - 1)
        xPosition = min(xPosition, self.xOffset + self.dayWidth * self.parent.columns - 1)
        
        if self.parent.blockItem.dayMode:
            startDay = self.parent.blockItem.selectedDate
        else:
            startDay = self.parent.blockItem.rangeStart
        # @@@ fixes Bug#1831, but doesn't really address the root cause
        # (the window is drawn with (0,0) virtual size on mac)
        if self.dayWidth > 0:
            deltaDays = (xPosition - self.xOffset) / self.dayWidth
        else:
            deltaDays = 0
        
        deltaHours = yPosition / self.hourHeight
        deltaMinutes = ((yPosition % self.hourHeight) * 60) / self.hourHeight
        deltaMinutes = int(deltaMinutes/15) * 15
        newTime = startDay + DateTime.RelativeDateTime(days=deltaDays,
                                                       hours=deltaHours,
                                                       minutes=deltaMinutes)
        return newTime

    def getPositionFromDateTime(self, datetime):
        if self.parent.blockItem.dayMode:
            startDay = self.parent.blockItem.selectedDate
        else:
            startDay = self.parent.blockItem.rangeStart
        
        delta = datetime - startDay
        x = (self.dayWidth * delta.day) + self.xOffset
        y = int(self.hourHeight * (datetime.hour + datetime.minute/float(60)))
        return (x, y)
        
class WeekBlock(CalendarBlock):
    def __init__(self, *arguments, **keywords):
        super(WeekBlock, self).__init__ (*arguments, **keywords)

    def initAttributes(self):
        if not self.hasLocalAttributeValue('rangeStart'):
            self.dayMode = False
            self.setRange(DateTime.today())
        if not self.hasLocalAttributeValue('rangeIncrement'):
            self.rangeIncrement = DateTime.RelativeDateTime(days=self.daysPerView)
            
    def instantiateWidget(self):
        # @@@ KCP move to a callback that gets called from parcel loader
        # after item has all of its attributes assigned from parcel xml
        self.initAttributes()
        
        return wxWeekPanel(self.parentBlock.widget,
                           Block.Block.getWidgetID(self))

    def setRange(self, date):
        if self.daysPerView == 7:
            # if in week mode, start at the beginning of the week
            delta = DateTime.RelativeDateTime(days=-6,
                                              weekday=(DateTime.Sunday, 0))
            self.rangeStart = date + delta
        else:
            # otherwise, stick with the given date
            self.rangeStart = date
            
        if self.dayMode:
            self.selectedDate = date
        else:
            self.selectedDate = self.rangeStart

class wxInPlaceEditor(wx.TextCtrl):
    def __init__(self, *arguments, **keywords):
        super(wxInPlaceEditor, self).__init__(style=wx.TE_PROCESS_ENTER | wx.NO_BORDER,
                                              *arguments, **keywords)
        
        self.item = None
        self.Bind(wx.EVT_TEXT_ENTER, self.OnTextEnter)
        self.Bind(wx.EVT_KILL_FOCUS, self.OnTextEnter)
        self.Hide()

        #self.editor.Bind(wx.EVT_CHAR, self.OnChar)
        parent = self.GetParent()
        parent.Bind(wx.EVT_SIZE, self.OnSize)

    def SaveItem(self):
        if self.item != None:
            self.item.displayName = self.GetValue()
        
    def OnTextEnter(self, event):
        self.SaveItem()
        self.Hide()
        event.Skip()

    def OnChar(self, event):
        if (event.KeyCode() == wx.WXK_RETURN):
            if self.item != None:
                self.item.displayName = self.GetValue()
            self.Hide()
        event.Skip()

    def SetItem(self, item, position, size, pointSize):
        self.item = item
        self.SetValue(item.displayName)

        newSize = wx.Size(size.width, size.height)

        # GTK doesn't like making the editor taller than
        # the font, plus it doesn't honor the NOBORDER style
        # so we have to include 4 pixels for each border
        if '__WXGTK__' in wx.PlatformInfo:
            newSize.height = pointSize + 8

        self.SetSize(newSize)
        self.Move(position)

        self.SetInsertionPointEnd()
        self.SetSelection(-1, -1)
        self.Show()
        self.SetFocus()

    def OnSize(self, event):
        self.Hide()
        event.Skip()

class wxMonthCanvas(CollectionCanvas.wxCollectionCanvas, CalendarEventHandler):
    def __init__(self, *arguments, **keywords):
        super(wxMonthCanvas, self).__init__(*arguments, **keywords)

    def OnInit(self):

        # Setup the navigation buttons
        today = DateTime.today()
        
        self.prevButton = CollectionCanvas.CanvasBitmapButton(self, "application/images/backarrow.png")
        self.nextButton = CollectionCanvas.CanvasBitmapButton(self, "application/images/forwardarrow.png")
        self.todayButton = CollectionCanvas.CanvasTextButton(self, today.Format("%b %d, %Y"),
                                                             self.bigFont, self.bigFontColor,
                                                             self.bgColor)
        self.monthButton = CollectionCanvas.CanvasTextButton(self, today.Format("%B %Y"),
                                                             self.bigFont, self.bigFontColor,
                                                             self.bgColor)

        self.todayButton.UpdateSize()
        self.monthButton.UpdateSize()

        box = wx.BoxSizer(wx.HORIZONTAL)
        box.Add((0,0), 1, wx.EXPAND, 5)
        box.Add((0,0), 1, wx.EXPAND, 5)
        box.Add(self.monthButton, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)
        box.Add((0,0), 1, wx.EXPAND, 5)
        box.Add(self.todayButton, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        box.Add(self.prevButton, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)
        box.Add(self.nextButton, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)
        self.SetSizer(box)
                                            
        self.Bind(wx.EVT_BUTTON, self.OnPrev, self.prevButton)
        self.Bind(wx.EVT_BUTTON, self.OnNext, self.nextButton)
        self.Bind(wx.EVT_BUTTON, self.OnToday, self.todayButton)
        self.Bind(wx.EVT_SIZE, self.OnSize)

    def OnSize(self, event):
        self.Refresh()
        event.Skip()

    def wxSynchronizeWidget(self):
        self.monthButton.SetLabel(self.blockItem.rangeStart.Format("%B %Y"))
        self.Layout()
        self.Refresh()

    # Drawing logic

    def _doDrawingCalculations(self):
        self.size = self.GetVirtualSize()
        self.yOffset = 50
        self.dayWidth = self.size.width / 7
        self.dayHeight = (self.size.height - self.yOffset) / 6
    
    def DrawBackground(self, dc):
        self._doDrawingCalculations()

        # Use the transparent pen for drawing the background rectangles
        dc.SetPen(wx.TRANSPARENT_PEN)

        # Draw the background
        dc.SetBrush(wx.WHITE_BRUSH)
        dc.DrawRectangle(0, 0, self.size.width, self.size.height + 10)
        
        # Set up pen for drawing the grid
        dc.SetPen(wx.Pen(wx.Colour(204, 204, 204)))

        # Draw the lines between the days
        for i in range(1, 7):
            dc.DrawLine(self.dayWidth * i, self.yOffset,
                        self.dayWidth * i, self.size.height)

        # Draw the lines between the weeks
        for i in range(6):
            dc.DrawLine(0, (i * self.dayHeight) + self.yOffset,
                        self.size.width,
                         (i * self.dayHeight) + self.yOffset)


    def DrawCells(self, dc):
        self._doDrawingCalculations()
        self.canvasItemList = []
        
        # Delegate the drawing of each day
        startDay = self.blockItem.rangeStart + \
                   DateTime.RelativeDateTime(days=-6, weekday=(DateTime.Sunday, 0))

        # Draw each day in the month
        for week in range(6):
            for day in range(7):
                currentDate = startDay + DateTime.RelativeDateTime(days=(week*7 + day))
                rect = wx.Rect(self.dayWidth * day,
                               self.dayHeight * week + self.yOffset,
                               self.dayWidth,
                               self.dayHeight)
                self.DrawDay(dc, currentDate, rect)

        # Draw the weekdays
        for i in range(7):
            weekday = startDay + DateTime.RelativeDateTime(days=i)
            rect = wx.Rect(self.dayWidth * i,
                           self.yOffset - 20,
                           self.dayWidth, 20) # Related to font height?
            self.DrawWeekday(dc, weekday, rect)


    def DrawDay(self, dc, date, rect):
        # Scaffolding, we'll get more sophisticated here

        dc.SetTextForeground(self.bigFontColor)
        dc.SetFont(self.bigFont)

        # Draw the day header
        # Add logic to treat "today" or "not in current month" specially
        dc.DrawText(date.Format("%d"), rect.x, rect.y)
        
        x = rect.x
        y = rect.y + 10
        w = rect.width
        h = 15

        dc.SetTextForeground(self.smallFontColor)
        dc.SetFont(self.smallFont)

        for item in self.blockItem.getItemsByDate(date):
            itemRect = wx.Rect(x, y, w, h)
            canvasItem = CollectionCanvas.CanvasItem(itemRect, item)
            self.canvasItemList.append(canvasItem)

            # keep track of the current drag/resize box
            if self._currentDragBox and self._currentDragBox.item == item:
                self._currentDragBox = canvasItem
                
            if (self.blockItem.selection is item):
                dc.SetPen(wx.BLACK_PEN)
                dc.SetBrush(wx.WHITE_BRUSH)
                dc.DrawRectangleRect(itemRect)
                
            self.DrawWrappedText(dc, item.displayName, itemRect)
            y += h

    def DrawWeekday(self, dc, weekday, rect):
        dc.SetTextForeground(self.bigFontColor)
        dc.SetFont(self.bigFont)

        dayName = weekday.Format('%a')
        self.DrawCenteredText(dc, dayName, rect)

    # handle mouse related actions: move, create

    def OnCreateItem(self, unscrolledPosition, createOnDrag):
        if not createOnDrag:
            # @@@ this code might want to live somewhere else, refactored
            view = self.blockItem.itsView
            newTime = self.getDateTimeFromPosition(unscrolledPosition)
            event = Calendar.CalendarEvent(view=view)
            event.InitOutgoingAttributes()
            event.ChangeStart(DateTime.DateTime(newTime.year, newTime.month,
                                                newTime.day,
                                                event.startTime.hour,
                                                event.startTime.minute))
            self.OnSelectItem(event)
            
            # @@@ Bug#1854 currently this is too slow,
            # and the event causes flicker
            view.commit()
        return None

    def OnDraggingItem(self, unscrolledPosition):
        newTime = self.getDateTimeFromPosition(unscrolledPosition)
        item = self._currentDragBox.getItem()
        if (newTime.absdate != item.startTime.absdate):
            item.ChangeStart(DateTime.DateTime(newTime.year, newTime.month,
                                               newTime.day,
                                               item.startTime.hour,
                                               item.startTime.minute))
            self.Refresh()

    def getDateTimeFromPosition(self, position):
        # x and y in whole canvas coordinates
        
        # the first day displayed in the month view
        startDay = self.blockItem.getStartDay()

        # the number of days over
        deltaDays = position.x / self.dayWidth

        # the number of weeks over
        deltaWeeks = (position.y - self.yOffset) / self.dayHeight

        newDay = startDay + DateTime.RelativeDateTime(days=deltaDays,
                                                      weeks=deltaWeeks)
        return newDay
    

class MonthBlock(CalendarBlock):
    def __init__(self, *arguments, **keywords):
        super(MonthBlock, self).__init__(*arguments, **keywords)

        self.rangeIncrement = DateTime.RelativeDateTime(months=1)
        self.setRange(DateTime.today())

    def instantiateWidget(self):
        return wxMonthCanvas(self.parentBlock.widget,
                             Block.Block.getWidgetID(self))

    def setRange(self, date):
        # override set range to pick the first day of the month
        self.rangeStart = DateTime.DateTime(date.year, date.month)
        self.selectedDate = self.rangeStart

    def getStartDay(self):
        """ Returns the starting day of the month displayed.
        """
        startDay = self.rangeStart + \
                   DateTime.RelativeDateTime(days=-6,
                                             weekday=(DateTime.Sunday, 0))
        return startDay



    







