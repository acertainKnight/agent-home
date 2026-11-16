// Usage: osascript -l JavaScript badge-icon.js <source.app> <badge> <target>
// Attaches the source app's icon to the target as its Finder custom icon. A
// non-empty badge (one or two characters) is drawn on a white disc at the
// lower right.
ObjC.import('AppKit');

function run(argv) {
  var source = argv[0], badge = argv[1], target = argv[2];
  var S = 1024;
  var base = $.NSWorkspace.sharedWorkspace.iconForFile(source);

  var rep = $.NSBitmapImageRep.alloc.initWithBitmapDataPlanesPixelsWidePixelsHighBitsPerSampleSamplesPerPixelHasAlphaIsPlanarColorSpaceNameBytesPerRowBitsPerPixel(
    null, S, S, 8, 4, true, false, $.NSDeviceRGBColorSpace, 0, 0);
  $.NSGraphicsContext.saveGraphicsState;
  // Assigning the currentContext property draws nothing; the setter call does.
  $.NSGraphicsContext.setCurrentContext($.NSGraphicsContext.graphicsContextWithBitmapImageRep(rep));

  base.drawInRectFromRectOperationFraction(
    $.NSMakeRect(0, 0, S, S), $.NSZeroRect, $.NSCompositingOperationSourceOver, 1.0);

  if (badge) {
    var d = S * 0.40, x = S * 0.54, y = S * 0.06;
    $.NSColor.whiteColor.setFill;
    $.NSBezierPath.bezierPathWithOvalInRect($.NSMakeRect(x, y, d, d)).fill;

    var attrs = $.NSMutableDictionary.alloc.init;
    attrs.setObjectForKey($.NSFont.boldSystemFontOfSize(d * (badge.length > 1 ? 0.44 : 0.62)), $.NSFontAttributeName);
    attrs.setObjectForKey($.NSColor.colorWithSRGBRedGreenBlueAlpha(0.11, 0.11, 0.12, 1), $.NSForegroundColorAttributeName);
    var text = $(badge);
    var size = text.sizeWithAttributes(attrs);
    text.drawAtPointWithAttributes(
      $.NSMakePoint(x + (d - size.width) / 2, y + (d - size.height) / 2), attrs);
  }

  $.NSGraphicsContext.restoreGraphicsState;

  var img = $.NSImage.alloc.initWithSize($.NSMakeSize(S, S));
  img.addRepresentation(rep);
  return $.NSWorkspace.sharedWorkspace.setIconForFileOptions(img, target, 0) ? 'OK' : 'ERR set-icon-failed';
}
