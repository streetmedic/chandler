__parcel__ = "amazon"

import osaf.framework.blocks.Block as Block
import AmazonKinds
import application.Globals as Globals
import osaf.framework.blocks.detail.Detail as Detail

class AmazonController(Block.Block):
    def onNewAmazonCollectionEvent(self, event):
        return AmazonKinds.CreateCollection(self.itsView, Globals.views[0])

    def onNewAmazonWishListEvent(self, event):
        return AmazonKinds.CreateWishListCollection(self.itsView, Globals.views[0])

class ImageBlock(Detail.HTMLDetailArea):
    def getHTMLText(self, item):
        if item == item.itsView:
            return
        if item is not None:

            # make the html
            HTMLText = '<html><body>\n\n'
            HTMLText = HTMLText + '<img src = "' + str(item.imageURL) + '">\n\n</html></body>'
            return unicode(HTMLText)

 
