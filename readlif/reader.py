import struct
import xml.etree.ElementTree as ET
from PIL import Image
import warnings
import numpy as np

class LifImage:
    """
    This should not be called directly. This should be generated while calling
    get_image or get_iter_image from a LifFile object.

    Attributes:
        path (str): path / name of the image
        dims (tuple): (c, z, t, y, x, m)
        name (str): image name
        offsets (list): Byte position offsets for each image.
        filename (str): The name of the LIF file being read
        channels (int): Number of channels in the image
        nz (int): number of 'z' frames
        nt (int): number of 't' frames
        scale (tuple): (scale_x, scale_y, scale_z, scale_t).
            Conversion factor: px/nm for x, y and z; sec/image for t.
        info (dict): Direct access to data dict from LifFile, this is most
            useful for debugging. These are values pulled from the Leica XML.


    """

    def __init__(self, image_info, offsets, filename):
        self.dims = tuple(image_info["dims"])  # CZTMYX
        self.path = image_info["path"]
        self.offsets = offsets
        self.info = image_info
        self.filename = filename
        self.name = image_info["name"]
        self.channels = image_info["channels"]
        self.ch_offsets = image_info["ch_offsets"]
        self.nz = int(image_info["dims"][1])
        self.nt = int(image_info["dims"][2])
        self.scale = image_info["scale"]  # likely: image_info["scale"]
        self.stride = image_info["stride"]
        self.tile_positions = np.array(image_info["tile_positions"])
        self.dtype = np.dtype('u{}'.format(int(image_info["ch_resolutions"][0] / 8)))
        # TODO: DataType attribute
        # TODO: FlipX, FlipY, SwapXY
        # FIXME: TilePositions

    def _get_item_np(self, n):
        """
        Gets specified item from the image set (private).
        Args:
            n (int): what item to retrieve

        Returns:
            Plane as 2D numpy array.
        """

        n_planes = np.prod(self.dims[:4])
        if n >= n_planes:
            raise ValueError("Invalid item trying to be retrieved.")

        dims_yx = self.dims[-2:]

        with open(self.filename, "rb") as image:

            plane_size = np.int64(np.prod(dims_yx))
            plane_bytes = np.int64(plane_size * np.dtype(self.dtype).itemsize)
            offset = np.int64(self.offsets[0] + plane_bytes * n)

            im = np.fromfile(
                image,
                dtype=self.dtype,
                count=plane_size,
                offset=offset,
                )

        return np.reshape(im, dims_yx)

    def get_frame_np(self, z=0, t=0, c=0, m=0):
        """
        Gets the specified frame (z, t, c, m) from image.

        Args:
            z (int): z position
            t (int): time point
            c (int): channel
            m (int): tile

        Returns:
            Plane as 2D numpy array.
        """

        dims_yx = self.dims[-2:]

        offset = m * self.stride[3]
        offset += t * self.stride[2]
        offset += z * self.stride[1]
        offset += c * self.stride[0]

        with open(self.filename, "rb") as image:

            im = np.fromfile(
                image,
                dtype=self.dtype,
                count=int(np.prod(dims_yx)),
                offset=int(offset),
                )

        return np.reshape(im, dims_yx)

    def get_stack_np(self, m=0):
        """
        Gets the specified z-stack from image.

        Args:
            m (int): tile

        Returns:
            Z-stack as 4D (CZTYX) numpy array.
            TODO: check T insertion
        """

        m_idx = 3
        stackdims = self.dims[:m_idx] + self.dims[m_idx+1:]
        offset = self.offsets[0] + int(m * self.stride[m_idx])

        with open(self.filename, "rb") as image:

            im = np.fromfile(
                image,
                dtype=self.dtype,
                count=np.prod(stackdims),
                offset=offset,
                )

        return np.reshape(im, stackdims)

    def _get_item(self, n):
        """
        Gets specified item from the image set (private).
        Args:
            n (int): what item to retrieve

        Returns:
            PIL image
        """
        n = int(n)
        # Channels, times z, times t, times m.
        # This is the number of 'images' in the block.
        seek_distance = self.channels * self.dims[1] * self.dims[2] * self.dims[3]
        if n >= seek_distance:
            raise ValueError("Invalid item trying to be retrieved.")
        with open(self.filename, "rb") as image:

            # self.offsets[1] is the length of the image
            if self.offsets[1] == 0:
                # In the case of a blank image, we can calculate the length from
                # the metadata in the LIF. When this is read by the parser,
                # it is set to zero initially.
                image_len = seek_distance * self.dims[4] * self.dims[5]
            else:
                image_len = int(self.offsets[1] / seek_distance)

            # self.offsets[0] is the offset in the file
            image.seek(self.offsets[0] + image_len * n)

            # It is not necessary to read from disk for truncated files
            if self.offsets[1] == 0:
                data = b"\00" * image_len
            else:
                data = image.read(image_len)
            return Image.frombytes("L", (self.dims[4], self.dims[5]), data)

    def get_frame(self, z=0, t=0, c=0, m=0, return_as_np=False):
        """
        Gets the specified frame (z, t, c, m) from image.

        Args:
            z (int): z position
            t (int): time point
            c (int): channel
            m (int): tile

        Returns:
            Plane as 2D numpy array.
        """
        z = int(z)
        t = int(t)
        c = int(c)
        m = int(m)
        if z >= self.nz:
            raise ValueError("Requested Z frame doesn't exist.")
        elif t >= self.nt:
            raise ValueError("Requested T frame doesn't exist.")
        elif c >= self.channels:
            raise ValueError("Requested channel doesn't exist.")
        elif m >= self.dims[3]:
            raise ValueError("Requested tile doesn't exist.")

        total_items = self.channels * self.nz * self.nt * self.dims[3]

        m_offset =  self.channels * self.nz * self.nt
        m_requested = m_offset * m

        t_offset =  self.channels * self.nz
        t_requested = t_offset * t

        c_offset = self.nz
        c_requested = c_offset * c

        z_requested = z

        item_requested = m_requested + t_requested + z_requested + c_requested
        if item_requested > total_items:
            raise ValueError("The requested item is after the end of the image")

        if return_as_np:
            return self._get_item_np(item_requested)
        else:
            return self._get_item(item_requested)

    def get_frame_tmp(self, z=0, t=0, c=0, m=0, return_as_np=False):
        """
        Gets the specified frame (z, t, c, m) from image.

        Args:
            z (int): z position
            t (int): time point
            c (int): channel
            m (int): tile

        Returns:
            Plane as 2D numpy array.
        """
        z = int(z)
        t = int(t)
        c = int(c)
        m = int(m)
        if z >= self.nz:
            raise ValueError("Requested Z frame doesn't exist.")
        elif t >= self.nt:
            raise ValueError("Requested T frame doesn't exist.")
        elif c >= self.channels:
            raise ValueError("Requested channel doesn't exist.")
        elif m >= self.dims[3]:
            raise ValueError("Requested tile doesn't exist.")

        total_items = self.channels * self.nz * self.nt * self.dims[3]

        m_offset =  self.channels * self.nz * self.nt
        m_requested = m_offset * m

        t_offset =  self.channels * self.nz
        t_requested = t_offset * t

        z_offset = self.channels
        z_requested = z_offset * z

        c_requested = c

        item_requested = m_requested + t_requested + z_requested + c_requested
        if item_requested > total_items:
            raise ValueError("The requested item is after the end of the image")

        print(item_requested)
        if return_as_np:
            return self._get_item_np(item_requested)
        else:
            return self._get_item(item_requested)

    def get_iter_m(self, z=0, c=0, t=0):
        """
        Returns an iterator over tile m at time t, position z and channel c.

        Args:
            z (int): z position
            c (int): channel
            t (int): timepoint

        Returns:
            Iterator of 2D numpy arrays.
        """
        z = int(z)
        c = int(c)
        t = int(t)
        m = 0
        while m < self.dims[3]:
            yield self.get_frame(z=z, t=t, c=c, m=m)
            m += 1

    def get_iter_t(self, z=0, c=0, m=0):
        """
        Returns an iterator over time t at tile m, position z and channel c.

        Args:
            z (int): z position
            c (int): channel
            m (int): tile

        Returns:
            Iterator of 2D numpy arrays.
        """
        z = int(z)
        c = int(c)
        t = 0
        while t < self.nt:
            yield self.get_frame(z=z, t=t, c=c, m=m)
            t += 1

    def get_iter_c(self, z=0, t=0, m=0):
        """
        Returns an iterator over the channels at tile m, time t and position z.

        Args:
            z (int): z position
            t (int): time point
            m (int): tile

        Returns:
            Iterator of 2D numpy arrays.
        """
        t = int(t)
        z = int(z)
        m = int(m)
        c = 0
        while c < self.channels:
            yield self.get_frame(z=z, t=t, c=c, m=m)
            c += 1

    def get_iter_z(self, t=0, c=0, m=0):
        """
        Returns an iterator over the z series of tile m, time t and channel c.

        Args:
            t (int): time point
            c (int): channel
            m (int): tile

        Returns:
            Iterator of 2D numpy arrays.
        """
        t = int(t)
        c = int(c)
        m = int(m)
        z = 0
        while z < self.nz:
            yield self.get_frame(z=z, t=t, c=c, m=m)
            z += 1


def _read_long(handle):
    """Reads eight bytes, returns the long (Private)."""
    long_data, = struct.unpack("Q", handle.read(8))
    return long_data


def _check_truncated(handle):
    """Checks if the LIF file is truncated by reading in 100 bytes."""
    handle.seek(-4, 1)
    if handle.read(100) == (b"\x00" * 100):
        handle.seek(-100, 1)
        return True
    handle.seek(-100, 1)
    return False


def _check_magic(handle, bool_return=False):
    """Checks for lif file magic bytes (Private)."""
    if handle.read(4) == b"\x70\x00\x00\x00":
        return True
    else:
        if not bool_return:
            raise ValueError("This is probably not a LIF file. "
                             "Expected LIF magic byte at " + str(handle.tell()))
        else:
            return False


def _check_mem(handle, bool_return=False):
    """Checks for 'memory block' bytes (Private)."""
    if handle.read(1) == b"\x2a":
        return True
    else:
        if not bool_return:
            raise ValueError("Expected LIF memory byte at " + str(handle.tell()))
        else:
            return False


def _read_int(handle):
    """Reads four bytes, returns the int (Private)."""
    int_data, = struct.unpack("I", handle.read(4))
    return int_data


def _get_len(handle):
    """Returns total file length (Private)."""
    position = handle.tell()
    handle.seek(0, 2)
    file_len = handle.tell()
    handle.seek(position)
    return file_len


class LifFile:
    """
    Given a path to a lif file, returns objects containing
    the image and data.

    This is based on the java openmicroscopy bioformats lif reading code
    that is here: https://github.com/openmicroscopy/bioformats/blob/master/components/formats-gpl/src/loci/formats/in/LIFReader.java # noqa

    Attributes:
        xml_header (string): The LIF xml header with tons of data
        xml_root (ElementTree): ElementTree XML representation
        offsets (list): Byte positions of the files
        num_images (int): Number of images
        image_list (dict): Has the keys: path, folder_name, folder_uuid,
            name, image_id, frames


    Example:
        >>> from readlif.reader import LifFile
        >>> new = LifFile('./path/to/file.lif')

        >>> for image in new.get_iter_image():
        >>>     for frame in image.get_iter_t():
        >>>         frame.image_info['name']
        >>>         # do stuff
    """

    def _recursive_image_find(self, tree, return_list=None, path=""):
        """Creates list of images by parsing the XML header recursively"""

        if return_list is None:
            return_list = []

        children = tree.findall("./Children/Element")
        if len(children) < 1:  # Fix for 'first round'
            children = tree.findall("./Element")
        for item in children:
            folder_name = item.attrib["Name"]
            if path == "":
                appended_path = folder_name
            else:
                appended_path = path + "/" + folder_name
            has_sub_children = len(item.findall("./Children/Element")) > 0
            is_image = (
                len(item.findall("./Data/Image/ImageDescription/Dimensions")) > 0
            )

            if has_sub_children:
                self._recursive_image_find(item, return_list, appended_path)

            elif is_image:

                # Determine number of channels
                channel_list = item.findall(
                    "./Data/Image/ImageDescription/Channels/ChannelDescription"
                )
                n_channels = len(channel_list)
                ch_offsets = [np.uint64(channel_list[ch].attrib["BytesInc"])
                              for ch in range(n_channels)]
                ch_resolutions = [int(channel_list[ch].attrib["Resolution"])
                                  for ch in range(n_channels)]

                dims = [n_channels]
                strides = [ch_offsets[1]]  # FIXME: assumes at least 2 channels
                lengths = [float(n_channels - 1)]
                scales = [float(1)]

                for dim in [3, 4, 10, 2, 1]:  # C+ZTMYX
                    try:
                        dd = item.find(
                            "./Data/Image/ImageDescription/"
                            "Dimensions/"
                            "DimensionDescription"
                            '[@DimID="{}"]'.format(dim)
                        )
                        dims.append(int(dd.attrib["NumberOfElements"]))
                        strides.append(np.uint64(dd.attrib["BytesInc"]))
                        lengths.append(float(dd.attrib["Length"]))
                    except AttributeError:
                        dims.append(int(1))
                        strides.append(int(0))
                        lengths.append(float(1))

                scales.append( dims[1] / (lengths[1] * 10**6) )
                scales.append( dims[2] / lengths[2] )
                scales.append( float(1) )
                scales.append( (dims[4] - 1) / (lengths[4] * 10**6) )
                scales.append( (dims[5] - 1) / (lengths[5] * 10**6) )

                PosX, PosY = [], []
                tiles = item.findall("./Data/Image/Attachment/Tile")
                for tile in tiles:
                    PosX.append(float(tile.attrib["PosX"]) * 1e6)
                    PosY.append(float(tile.attrib["PosY"]) * 1e6)

                data_dict = {
                    "dims": dims,
                    "path": str(path + "/"),
                    "name": item.attrib["Name"],
                    "channels": n_channels,
                    "ch_offsets": ch_offsets,
                    "ch_resolutions": ch_resolutions,
                    "scale": scales,
                    "stride": strides,
                    "tile_positions": [PosX, PosY],
                }

                return_list.append(data_dict)

        return return_list

    def __init__(self, filename):
        self.filename = filename
        f = open(filename, "rb")
        f_len = _get_len(f)

        _check_magic(f)  # read 4 byte, check for magic bytes
        f.seek(8)
        _check_mem(f)  # read 1 byte, check for memory byte

        header_len = _read_int(f)  # length of the xml header
        self.xml_header = f.read(header_len * 2).decode("utf-16")
        self.xml_root = ET.fromstring(self.xml_header)

        self.offsets = []
        truncated = False
        while f.tell() < f_len:
            try:
                # To find offsets, read magic byte
                _check_magic(f)  # read 4 byte, check for magic bytes
                f.seek(4, 1)
                _check_mem(f)  # read 1 byte, check for memory byte

                block_len = _read_int(f)

                # Not sure if this works, as I don't have a file to test it on
                # This is based on the OpenMicroscopy LIF reader written in in java
                if not _check_mem(f, True):
                    f.seek(-5, 1)
                    block_len = _read_long(f)
                    _check_mem(f)

                description_len = _read_int(f) * 2

                if block_len > 0:
                    self.offsets.append((f.tell() + description_len, block_len))

                f.seek(description_len + block_len, 1)

            except ValueError:
                if _check_truncated(f):
                    truncation_begin = f.tell()
                    warnings.warn("LIF file is likely truncated. Be advised, "
                                  "it appears that some images are blank. ",
                                  UserWarning)
                    truncated = True
                    f.seek(0, 2)

                else:
                    raise

        f.close()

        self.image_list = self._recursive_image_find(self.xml_root)

        # If the image is truncated we need to manually add the offsets because
        # the LIF magic bytes aren't present to guide the location.
        if truncated:
            num_truncated = len(self.image_list) - len(self.offsets)
            for i in range(num_truncated):
                # In the special case of a truncation,
                # append an offset with length zero.
                # This will be taken care of later when the images are retrieved.
                self.offsets.append((truncation_begin, 0))

        if len(self.image_list) != len(self.offsets) and not truncated:
            raise ValueError("Number of images is not equal to number of "
                             "offsets, and this file does not appear to "
                             "be truncated. Something has gone wrong.")
        else:
            self.num_images = len(self.image_list)

    def get_image(self, img_n=0):
        """
        Specify the image number, and this returns a LifImage object
        of that image.

        Args:
            img_n (int): Image number to retrieve

        Returns:
            LifImage object with specified image
        """
        img_n = int(img_n)
        if img_n >= len(self.image_list):
            raise ValueError("There are not that many images!")
        offsets = self.offsets[img_n]
        image_info = self.image_list[img_n]
        return LifImage(image_info, offsets, self.filename)

    def get_iter_image(self, img_n=0):
        """
        Returns an iterator of LifImage objects in the lif file.

        Args:
            img_n (int): Image to start iteration at

        Returns:
            Iterator of LifImage objects.
        """
        img_n = int(img_n)
        while img_n < len(self.image_list):
            offsets = self.offsets[img_n]
            image_info = self.image_list[img_n]
            yield LifImage(image_info, offsets, self.filename)
            img_n += 1
