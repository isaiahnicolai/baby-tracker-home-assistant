"""
Preparing a photo for an entry the way the Android app stores one.

A Picture is a file `<fileName>.jpg` beside a thumbnail `<fileName>__thumbnail.jpg`
(Picture.getFileFullName / getThumbnailFullName, DefaultValues.ThumbnailPost) in the
app's picture folder, where fileName is the Picture's own UUID. The app scales the
photo to about 1.5 screens (BitmapUtilities.copyImageFileWithScale) and writes the
thumbnail from the view it showed, so there is no fixed thumbnail size; ours keeps
the aspect ratio within THUMBNAIL_SIZE.

Pillow is only needed here, so it is imported when a photo is added.
"""
import os
import shutil
import uuid

from .records import THUMBNAIL_SUFFIX

MAX_PHOTO_SIZE = 2048     # longest side of the stored photo, in pixels
THUMBNAIL_SIZE = 400      # longest side of the thumbnail
PHOTO_QUALITY = 85
THUMBNAIL_QUALITY = 90


class PhotoError(Exception):
    """A photo could not be read or converted."""


def _pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError as err:
        raise PhotoError("Adding photos needs Pillow: pip install 'babytracker-client[photos]'") from err
    return Image, ImageOps


def _save_jpeg(image, path, quality, max_side):
    image.thumbnail((max_side, max_side))
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(path, "JPEG", quality=quality)


def import_photo(source, picture_dir):
    """
    Copy an image into picture_dir under a new UUID, as a JPEG with a thumbnail.

    Returns (file_name, photo_path, thumbnail_path); file_name is the Picture's fileName
    (and objectID). Anything Pillow can open is accepted (PNG, WebP, HEIC if installed...).
    A JPEG that is small enough and upright is copied byte for byte.
    """
    Image, ImageOps = _pillow()
    file_name = str(uuid.uuid4()).upper()
    photo_path = os.path.join(picture_dir, f"{file_name}.jpg")
    thumbnail_path = os.path.join(picture_dir, f"{file_name}{THUMBNAIL_SUFFIX}")
    os.makedirs(picture_dir, exist_ok=True)
    try:
        with Image.open(source) as opened:
            opened.load()
            rotated = opened.getexif().get(0x0112, 1) not in (0, 1)
            upright = ImageOps.exif_transpose(opened)
            if opened.format == "JPEG" and not rotated and max(opened.size) <= MAX_PHOTO_SIZE:
                shutil.copyfile(source, photo_path)
            else:
                _save_jpeg(upright.copy(), photo_path, PHOTO_QUALITY, MAX_PHOTO_SIZE)
            _save_jpeg(upright.copy(), thumbnail_path, THUMBNAIL_QUALITY, THUMBNAIL_SIZE)
    except Exception as err:
        for path in (photo_path, thumbnail_path):
            if os.path.exists(path):
                os.remove(path)
        raise PhotoError(f"Could not read {source} as an image: {err}") from err
    return file_name, photo_path, thumbnail_path
