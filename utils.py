import string, binascii, sys, re, inspect

def represent_binary_fancy(len, value, mask = 0):
    result = []
    for i in range(len):
        if i%4 == 0:
            result.append( " " )
        if i%8 == 0:
            result.append( " " )
        if mask & 0x01:
            result.append( str(value & 0x01) )
        else:
            result.append( "." )
        mask = mask >> 1
        value = value >> 1
    result.reverse()
    
    return "".join(result).strip()

def parse_binary(value, bytemasks, verbose = False, value_len = 8):
    ## Parses a binary structure and gives information back
    ##  bytemasks is a sequence of (mask, value, string_if_no_match, string_if_match) tuples
    result = []
    for mask, byte, nonmatch, match in bytemasks:
        
        if verbose:
            prefix = represent_binary_fancy(value_len, value, mask) + ": "
        else:
            prefix = ""
        if (value & mask) == (byte & mask):
            if match is not None:
                result.append(prefix + match)
        else:
            if nonmatch is not None:
                result.append(prefix + nonmatch)
    
    return result

_myprintable = " " + string.letters + string.digits + string.punctuation
def hexdump(data, indent = 0, short = False, linelen = 16, offset = 0):
    r"""Generates a nice hexdump of data and returns it. Consecutive lines will 
    be indented with indent spaces. When short is true, will instead generate 
    hexdump without adresses and on one line.
    
    Examples: 
    hexdump('\x00\x41') -> \
    '0000:  00 41                                             .A              '
    hexdump('\x00\x41', short=True) -> '00 41 (.A)'"""
    
    def hexable(data):
        return " ".join([binascii.b2a_hex(a) for a in data])
    
    def printable(data):
        return "".join([e in _myprintable and e or "." for e in data])
    
    if short:
        return "%s (%s)" % (hexable(data), printable(data))
    
    FORMATSTRING = "%04x:  %-"+ str(linelen*3) +"s  %-"+ str(linelen) +"s"
    result = ""
    (head, tail) = (data[:linelen], data[linelen:])
    pos = 0
    while len(head) > 0:
        if pos > 0:
            result = result + "\n%s" % (' ' * indent)
        result = result + FORMATSTRING % (pos+offset, hexable(head), printable(head))
        pos = pos + len(head)
        (head, tail) = (tail[:linelen], tail[linelen:])
    return result

LIFE_CYCLES = {0x01: "Load file = loaded",
    0x03: "Applet instance / security domain = Installed",
    0x07: "Card manager = Initialized; Applet instance / security domain = Selectable",
    0x0F: "Card manager = Secured; Applet instance / security domain = Personalized",
    0x7F: "Card manager = Locked; Applet instance / security domain = Blocked",
    0xFF: "Applet instance = Locked"}

def parse_status(data):
    """Parses the Response APDU of a GetStatus command."""
    def parse_segment(segment):
        def parse_privileges(privileges):
            if privileges == 0x0:
                return "N/A"
            else:
                privs = []
                if privileges & (1<<7):
                    privs.append("security domain")
                if privileges & (1<<6):
                    privs.append("DAP DES verification")
                if privileges & (1<<5):
                    privs.append("delegated management")
                if privileges & (1<<4):
                    privs.append("card locking")
                if privileges & (1<<3):
                    privs.append("card termination")
                if privileges & (1<<2):
                    privs.append("default selected")
                if privileges & (1<<1):
                    privs.append("global PIN modification")
                if privileges & (1<<0):
                    privs.append("mandated DAP verification")
                return ", ".join(privs)
        
        lgth = ord(segment[0])
        aid = segment[1:1+lgth]
        lifecycle = ord(segment[1+lgth])
        privileges = ord(segment[1+lgth+1])
        
        print "aid length:       %i (%x)" % (lgth, lgth)
        print "aid:              %s" % hexdump(aid, indent = 18, short=True)
        print "life cycle state: %x (%s)" % (lifecycle, LIFE_CYCLES.get(lifecycle, "unknown or invalid state"))
        print "privileges:       %x (%s)\n" % (privileges, parse_privileges(privileges))

    pos = 0
    while pos < len(data):
        lgth = ord(data[pos])+3
        segment = data[pos:pos+lgth]
        parse_segment(segment)
        pos = pos + lgth

def _unformat_hexdump(dump):
    hexdump = " ".join([line[7:54] for line in dump.splitlines()])
    return binascii.a2b_hex("".join([e != " " and e or "" for e in hexdump]))

def _make_byte_property(prop):
    "Make a byte property(). This is meta code."
    return property(lambda self: getattr(self, "_"+prop, getattr(self, "_DEFAULT_"+prop, None)),
            lambda self, value: self._setbyte(prop, value), 
            lambda self: delattr(self, "_"+prop),
            "The %s attribute of the APDU" % prop)

def _make_bool_property(prop):
    "Make a bool property(). This is meta code."
    return property(lambda self: getattr(self, "_"+prop, getattr(self, "_DEFAULT_"+prop, None)),
            lambda self, value: self._setbool(prop, value), 
            lambda self: delattr(self, "_"+prop),
            "The %s attribute of the APDU" % prop)

class APDU(object):
    "Base class for an APDU"
    
    def __init__(self, *args, **kwargs):
        """Creates a new APDU instance. Can be given positional parameters which 
        must be sequences of either strings (or strings themselves) or integers
        specifying byte values that will be concatenated in order. Alternatively
        you may give exactly one positional argument that is an APDU instance.
        After all the positional arguments have been concatenated they must
        form a valid APDU!
        
        The keyword arguments can then be used to override those values.
        Keywords recognized are: 
            C_APDU: cla, ins, p1, p2, lc, le, data
            R_APDU: sw, sw1, sw2, data
        """
        
        initbuff = list()
        
        if len(args) == 1 and isinstance(args[0], self.__class__):
            self.parse( args[0].render() )
        else:
            for arg in args:
                if type(arg) == str:
                    initbuff.extend(arg)
                elif hasattr(arg, "__iter__"):
                    for elem in arg:
                        if hasattr(elem, "__iter__"):
                            initbuff.extend(elem)
                        else:
                            initbuff.append(elem)
                else:
                    initbuff.append(arg)
            
            for (index, value) in enumerate(initbuff):
                t = type(value)
                if t == str:
                    initbuff[index] = ord(value)
                elif t != int:
                    raise TypeError, "APDU must consist of ints or one-byte strings, not %s (index %s)" % (t, index)
            
            self.parse( initbuff )
        
        for (name, value) in kwargs.items():
            if value is not None:
                setattr(self, name, value)
    
    def _getdata(self):
        return getattr(self, "_data", "")
    def _setdata(self, value): 
        if isinstance(value, str):
            self._data = "".join([e for e in value])
        elif isinstance(value, list):
            self._data = "".join([chr(int(e)) for e in value])
        else:
            raise ValueError, "'data' attribute can only be a str or a list of int, not %s" % type(value)
        self.Lc = len(value)
    def _deldata(self):
        del self._data; self.data = ""
    
    data = property(_getdata, _setdata, None,
        "The data contents of this APDU")
    
    def _setbyte(self, name, value):
        #print "setbyte(%r, %r)" % (name, value)
        if isinstance(value, int):
            setattr(self, "_"+name, value)
        elif isinstance(value, str):
            setattr(self, "_"+name, ord(value))
        else:
            raise ValueError, "'%s' attribute can only be a byte, that is: int or str, not %s" % (namelower, type(value))

    def _setbool(self, name, value):
        #print "setbool(%r, %r)" % (name, value)
        if isinstance(value, bool):
            setattr(self, "_"+name, value)
        else:
            raise ValueError, "'%s' attribute can only be a bool, not %s" % (namelower, type(value))

    def _format_parts(self, fields):
        "utility function to be used in __str__ and __repr__"
        
        parts = []
        for i in fields:
            parts.append( "%s=0x%02X" % (i, getattr(self, i)) )
        
        return parts
    
    def __str__(self):
        result = "%s(%s)" % (self.__class__.__name__, ", ".join(self._format_fields()))
        
        if len(self.data) > 0:
            result = result + " with %i (0x%02x) bytes of data" % (
                len(self.data), len(self.data) 
            )
            return result + ":\n" + hexdump(self.data)
        else:
            return result
    
    def __repr__(self):
        parts = self._format_fields()
        
        if len(self.data) > 0:
            parts.append("data=%r" % self.data)
        
        return "%s(%s)" % (self.__class__.__name__, ", ".join(parts))

class C_APDU(APDU):
    "Class for a command APDU"
    
    def parse(self, apdu):
        "Parse a full command APDU and assign the values to our object, overwriting whatever there was."
        
        apdu = map( lambda a: (isinstance(a, str) and (ord(a),) or (a,))[0], apdu)
        apdu = apdu + [0] * max(4-len(apdu), 0)
        
        self.CLA, self.INS, self.P1, self.P2 = apdu[:4] # case 1, 2, 3, 4
	self.ext = False
        if len(apdu) == 5:                              # case 2
            self.Le = apdu[-1]
            self.data = ""
	elif len(apdu) == 7 and apdu[4] == 0x00:	# case 2 extended
	    self.Le = apdu[6]
	    self.Le += apdu[5] << 8
	    self.data = ""
	    self.ext = True
        elif len(apdu) > 5:                             # case 3, 4
	    if apdu[4] == 0x00:				# lc extended
	        self.Lc = apdu[6]
		self.Lc += apdu[5] << 8
                self.data = apdu[7:7 + self.Lc]
		self.ext = True
	        if 4 + 3 + self.Lc + 2 == len(apdu):	# case 4 extended
	            self.Le = apdu[-1]
		    self.Le += apdu[-2] << 8 #[7 + self.Lc:]
                elif 4 + 3 + self.Lc != len(apdu):	# case 3 extended
	            raise ValueError, "Invalid extended Lc value. Is %s, should be %s or %s" % (self.Lc,
                        len(apdu) - 7, len(apdu) - (7 + 2))
	    else:
                self.Lc = apdu[4]
                if len(apdu) == 5 + self.Lc:            # case 3
                    self.data = apdu[5:]
                elif len(apdu) == 5 + self.Lc + 1:      # case 4
                    self.data = apdu[5:-1]
                    self.Le = apdu[-1]
                else:
                    raise ValueError, "Invalid Lc value. Is %s, should be %s or %s" % (self.Lc,
                        len(apdu) - 5, len(apdu) - (5 + 1))
        else:                                           # case 1
            self.data = ""
    
    CLA = _make_byte_property("CLA"); cla = CLA
    INS = _make_byte_property("INS"); ins = INS
    P1 = _make_byte_property("P1");   p1 = P1
    P2 = _make_byte_property("P2");   p2 = P2
    Lc = _make_byte_property("Lc");   lc = Lc
    Le = _make_byte_property("Le");   le = Le
    Ext = _make_bool_property("Ext");   ext = Ext
    
    def _format_fields(self):
        fields = ["CLA", "INS", "P1", "P2"]
        if self.Lc > 0:
            fields.append("Lc")
        if hasattr(self, "_Le"): ## There's a difference between "Le = 0" and "no Le"
            fields.append("Le")
        
        return self._format_parts(fields)
    
    def render(self):
        "Return this APDU as a binary string"
        buffer = []
        
        for i in self.CLA, self.INS, self.P1, self.P2:
            buffer.append(chr(i))
        
	if self.Ext == False:
            if len(self.data) > 0:
                buffer.append(chr(self.Lc))
                buffer.append(self.data)
        
            if hasattr(self, "_Le"):
                buffer.append(chr(self.Le))
	else:
	    if len(self.data) > 0:
	        buffer.append(chr(0x0))
		buffer.append(chr(self.Lc >> 8))
                buffer.append(chr(self.Lc & 0xFF))
                buffer.append(self.data)
        
            if hasattr(self, "_Le"):
	        if len(self.data) == 0:
	            buffer.append(chr(0x0))
		buffer.append(chr(self.Le >> 8))
                buffer.append(chr(self.Le & 0xFF))
        
        return "".join(buffer)
    
    def case(self):
        "Return 1, 2, 3 or 4, depending on which ISO case we represent.	Add 4 in case of extended APDU."
	if self.Ext == False:
            if self.Lc == 0:
                if not hasattr(self, "_Le"):
                    return 1
                else:
                    return 2
            else:
                if not hasattr(self, "_Le"):
                    return 3
                else:
                    return 4
	else:
	    if self.Lc == 0:
                if not hasattr(self, "_Le"):
                    return 5 #? kind of senseless
                else:
                    return 6
            else:
                if not hasattr(self, "_Le"):
                    return 7
                else:
                    return 8
    
    _apduregex = re.compile(r'^\s*([0-9a-f]{2}\s*){4,}$', re.I)
    _fancyapduregex = re.compile(r'^\s*([0-9a-f]{2}\s*){4,}\s*((xx|yy)\s*)?(([0-9a-f]{2}|:|\)|\(|\[|\])\s*)*$', re.I)
    @staticmethod
    def parse_fancy_apdu(ext, *args):
        apdu_string = " ".join(args)
        if not C_APDU._fancyapduregex.match(apdu_string):
            raise ValueError
        
        apdu_string = apdu_string.lower()
        have_le = False
        pos = apdu_string.find("xx")
        if pos == -1:
            pos = apdu_string.find("yy")
            have_le = True
        
        apdu_head = ""
        apdu_tail = apdu_string
        if pos != -1:
            apdu_head = apdu_string[:pos]
            apdu_tail = apdu_string[pos+2:]
        
        if apdu_head.strip() != "" and not C_APDU._apduregex.match(apdu_head):
            raise ValueError
        
        class Node(list):
            def __init__(self, parent = None, type = None):
                list.__init__(self)
                self.parent = parent
                self.type = type
            
            def make_binary(self):
                "Recursively transform hex strings to binary"
                for index, child in enumerate(self):
                    if isinstance(child,str):
                        child = "".join( ("".join(child.split())).split(":") )
                        assert len(child) % 2 == 0
                        self[index] = binascii.a2b_hex(child)
                    else:
                        child.make_binary()
            
            def calculate_lengths(self):
                "Recursively calculate lengths and insert length counts"
                self.length = 0
                index = 0
                while index < len(self): ## Can't use enumerate() due to the insert() below
                    child = self[index]
                    
                    if isinstance(child,str):
                        self.length = self.length + len(child)
                    else:
                        child.calculate_lengths()
			if child.length < 256:
                            formatted_len = binascii.a2b_hex("%02x" % child.length) 
			else:
			    formatted_len = binascii.a2b_hex("%04x" % child.length)
                        self.length = self.length + len(formatted_len) + child.length
                        self.insert(index, formatted_len)
                        index = index + 1
                    
                    index = index + 1
            
            def flatten(self, offset = 0, ignore_types=["("]):
                "Recursively flatten, gather list of marks"
                string_result = []
                mark_result = []
                for child in self:
                    if isinstance(child,str):
                        string_result.append(child)
                        offset = offset + len(child)
                    else:
                        start = offset
                        child_string, child_mark = child.flatten(offset, ignore_types)
                        string_result.append(child_string)
                        offset = end = offset + len(child_string)
                        if not child.type in ignore_types:
                            mark_result.append( (child.type, start, end) )
                        mark_result.extend(child_mark)
                
                return "".join(string_result), mark_result
        
        
        tree = Node()
        current = tree
        allowed_parens = {"(": ")", "[":"]"}
        
        for pos,char in enumerate(apdu_tail):
            if char in (" ", "a", "b", "c", "d", "e", "f",":") or char.isdigit():
                if len(current) > 0 and isinstance(current[-1],str):
                    current[-1] = current[-1] + char
                else:
                    current.append(str(char))
                
            elif char in allowed_parens.values():
                if current.parent is None:
                    raise ValueError
                if allowed_parens[current.type] != char:
                    raise ValueError
                
                current = current.parent
                
            elif char in allowed_parens.keys():
                current.append( Node(current, char) )
                current = current[-1]
                
            else:
                raise ValueError
        
        if current != tree:
            raise ValueError
        
        tree.make_binary()
        tree.calculate_lengths()
        
        apdu_head = apdu_head.strip()
        if apdu_head != "":
            l = tree.length
            if have_le:
	        if ext == True:
                    l = l - 2
                else:
                    l = l - 1
	    if ext == True:
	        formatted_len = "%06x" % l
	    else:
                formatted_len = "%02x" % l
            apdu_head = binascii.a2b_hex("".join( (apdu_head + formatted_len).split() ))
        
        apdu_tail, marks = tree.flatten(offset=0)
        
        apdu = C_APDU(apdu_head + apdu_tail, marks = marks)
        return apdu


class R_APDU(APDU):
    "Class for a response APDU"
    
    def _getsw(self):        return chr(self.SW1) + chr(self.SW2)
    def _setsw(self, value):
        if len(value) != 2:
            raise ValueError, "SW must be exactly two bytes"
        self.SW1 = value[0]
        self.SW2 = value[1]
    
    SW = property(_getsw, _setsw, None,
        "The Status Word of this response APDU")
    sw = SW
    
    SW1 = _make_byte_property("SW1"); sw1 = SW1
    SW2 = _make_byte_property("SW2"); sw2 = SW2
    
    def parse(self, apdu):
        "Parse a full response APDU and assign the values to our object, overwriting whatever there was."
        if len(apdu) == 0: # To be filled in later
            return
        
        self.SW = apdu[-2:]
        self.data = apdu[:-2]
    
    def _format_fields(self):
        fields = ["SW1", "SW2"]
        return self._format_parts(fields)
    
    def render(self):
        "Return this APDU as a binary string"
        return self.data + self.sw

class Raw_APDU(APDU):
    """Raw APDU that doesn't do any parsing"""
    
    def parse(self, apdu):
        "'Parse' the apdu and copy the values to this object"
        self.data = apdu
    
    def render(self):
        "Return this APDU as a binary string"
        return self.data
    
    def _format_fields(self):
        return ""

class PN532_Frame(APDU):
    """This is not really an ISO 7816 APDU, but close enough to use the same
    class infrastructure."""
    
    def __init__(self, *args, **kwargs):
        """If applicable: redirect instance creation to a subclass"""
        super(PN532_Frame, self).__init__(*args, **kwargs)
        self._autosubclass()
    
    def _autosubclass(self):
        """If a more appropriate subclass is known about, change __class__ to 
        point to that class."""
        
        # Find all global classes that are a (possibly indirect) subclass of the current class
        candidates = [ e for e in globals().values() 
                      if inspect.isclass(e) and issubclass(e, self.__class__)
                      and not e == self.__class__ ]
        
        # For each candidate: Find if it specifies any matching rules
        # through class variables called MATCH_BY_* where * may be any field
        # and if so, remove those classes that don't match. Also count the number
        # of matches, to determine the best match
        matches = {}
        for candidate in candidates:
            m = 0
            for var in dir(candidate):
                if var.startswith("MATCH_BY_"):
                    fieldname = var[len("MATCH_BY_"):]
                    if getattr(self, fieldname) == getattr(candidate, var):
                        m = m + 1
                    else:
                        m = -1
                        break
            if m != -1:
                matches[candidate] = m
        
        if len(matches) > 0:
            # Remove all candidates that don't have maximal score
            max_score = max(matches.values())
            candidates = [ k for k,v in matches.items() if v == max_score ]
            
            # If there is still more than one candidate remaining, randomly choose
            # the first one.
            if len(candidates) > 0:
                c = candidates[0]
                if c != self.__class__:
                    self.__class__ = c
    
    DIR = _make_byte_property("DIR"); dir = DIR
    CMD = _make_byte_property("CMD"); cmd = CMD
    
    def parse(self, data):
        if len(data) > 0:
            self.dir = data[0]
        
        if len(data) > 1:
            self.cmd = data[1]
        
        if len(data) > 2:
            self.data = data[2:]
    
    def _format_fields(self):
        fields = ["DIR", "CMD"]
        return self._format_parts(fields)
    
    def render(self):
        return chr(self.cmd) + chr(self.dir) + self.data
    
class PN532_Command(PN532_Frame):
    MATCH_BY_dir = _DEFAULT_DIR = 0xd4

class PN532_Response(PN532_Frame):
    MATCH_BY_dir = _DEFAULT_DIR = 0xd5

class PN532_Target(object):
    TYPE_ISO14443A = "ISO 14443-A"
    TYPE_ISO14443B = "ISO 14443-B"
    def __init__(self, type):
        self.type = type
    
class PN532_Response_InListPassiveTarget(PN532_Response):
    MATCH_BY_cmd = _DEFAULT_CMD = 0x4b
    
    def parse_result(self, baudrate_polled):
        response = map(ord, self.data)
        self.targets = {}
        pos = 1
        last_pos = pos
        
        while pos < len(response):
            
            if baudrate_polled == 0:
                target = PN532_Target(PN532_Target.TYPE_ISO14443A)
                self.targets[response[pos]] = target
                
                target.sens_res = response[(pos+1):(pos+3)]
                target.sel_res = response[pos+3]
                
                pos = pos + 4
                if response[pos] > 0:
                    target.nfcid = response[pos+1:(pos+1+response[pos])]
                    pos = pos + response[pos]
                else:
                    target.nfcid = []
                pos = pos + 1 # NFCID length does not count length byte
                
                if len(response) > pos and response[pos] > 0:
                    target.ats = response[pos:(pos+response[pos])]
                    pos = pos + response[pos]
                else:
                    target.ats = []
                # ATS length does count length byte
            
            elif baudrate_polled == 3:
                target = PN532_Target(PN532_Target.TYPE_ISO14443B)
                self.targets[response[pos]] = target
                
                target.atqb = response[(pos+1):(pos+13)]
                pos = pos + 13
                
                if response[pos] > 0:
                    target.attrib_res = response[pos+1:(pos+1+response[pos])]
                    pos = pos + response[pos]
                else:
                    target.attrib_res = []
                pos = pos + 1 # ATTRIB_RES length does not count the length byte
            
            if last_pos == pos:
                return False
        
        return True

    

if __name__ == "__main__":
    response = """
0000:  07 A0 00 00 00 03 00 00 07 00 07 A0 00 00 00 62  ...............b
0010:  00 01 01 00 07 A0 00 00 00 62 01 01 01 00 07 A0  .........b......
0020:  00 00 00 62 01 02 01 00 07 A0 00 00 00 62 02 01  ...b.........b..
0030:  01 00 07 A0 00 00 00 03 00 00 01 00 0E A0 00 00  ................
0040:  00 30 00 00 90 07 81 32 10 00 00 01 00 0E A0 00  .0.....2........
0050:  00 00 30 00 00 90 07 81 42 10 00 00 01 00 0E A0  ..0.....B.......
0060:  00 00 00 30 00 00 90 07 81 41 10 00 00 07 00 0E  ...0.....A......
0070:  A0 00 00 00 30 00 00 90 07 81 12 10 00 00 01 00  ....0...........
0080:  09 53 4C 42 43 52 59 50 54 4F 07 00 90 00        .SLBCRYPTO....  
""" # 64kv1 vorher
    response = """
0000:  07 A0 00 00 00 03 00 00 0F 00 07 A0 00 00 00 62  ...............b
0010:  00 01 01 00 07 A0 00 00 00 62 01 01 01 00 07 A0  .........b......
0020:  00 00 00 62 01 02 01 00 07 A0 00 00 00 62 02 01  ...b.........b..
0030:  01 00 07 A0 00 00 00 03 00 00 01 00 08 A0 00 00  ................
0040:  00 30 00 CA 10 01 00 0E A0 00 00 00 30 00 00 90  .0..........0...
0050:  07 81 32 10 00 00 01 00 0E A0 00 00 00 30 00 00  ..2..........0..
0060:  90 07 81 42 10 00 00 01 00 0E A0 00 00 00 30 00  ...B..........0.
0070:  00 90 07 81 41 10 00 00 07 00 0E A0 00 00 00 30  ....A..........0
0080:  00 00 90 07 81 12 10 00 00 01 00 09 53 4C 42 43  ............SLBC
0090:  52 59 50 54 4F 07 00 90 00                       RYPTO....       
""" # komische Karte
    response = """
0000:  07 A0 00 00 00 03 00 00 07 00 07 A0 00 00 00 62  ...............b
0010:  00 01 01 00 07 A0 00 00 00 62 01 01 01 00 07 A0  .........b......
0020:  00 00 00 62 01 02 01 00 07 A0 00 00 00 62 02 01  ...b.........b..
0030:  01 00 07 A0 00 00 00 03 00 00 01 00 0E A0 00 00  ................
0040:  00 30 00 00 90 07 81 32 10 00 00 01 00 0E A0 00  .0.....2........
0050:  00 00 30 00 00 90 07 81 42 10 00 00 01 00 0E A0  ..0.....B.......
0060:  00 00 00 30 00 00 90 07 81 41 10 00 00 07 00 0E  ...0.....A......
0070:  A0 00 00 00 30 00 00 90 07 81 12 10 00 00 01 00  ....0...........
0080:  09 53 4C 42 43 52 59 50 54 4F 07 00 05 A0 00 00  .SLBCRYPTO......
0090:  00 01 01 00 90 00                                ......          
""" # 64kv1 nachher
    response = """
0000:  07 A0 00 00 00 03 00 00 07 00 07 A0 00 00 00 62  ...............b
0010:  00 01 01 00 07 A0 00 00 00 62 01 01 01 00 07 A0  .........b......
0020:  00 00 00 62 01 02 01 00 07 A0 00 00 00 62 02 01  ...b.........b..
0030:  01 00 07 A0 00 00 00 03 00 00 01 00 0E A0 00 00  ................
0040:  00 30 00 00 90 07 81 32 10 00 00 01 00 0E A0 00  .0.....2........
0050:  00 00 30 00 00 90 07 81 42 10 00 00 01 00 0E A0  ..0.....B.......
0060:  00 00 00 30 00 00 90 07 81 41 10 00 00 07 00 0E  ...0.....A......
0070:  A0 00 00 00 30 00 00 90 07 81 12 10 00 00 01 00  ....0...........
0080:  09 53 4C 42 43 52 59 50 54 4F 07 00 05 A0 00 00  .SLBCRYPTO......
0090:  00 01 01 00 06 A0 00 00 00 01 01 07 02 90 00     ............... 
""" # 64k1 nach setup
    #response = sys.stdin.read()
    #parse_status(_unformat_hexdump(response)[:-2])
    
    a = C_APDU(1,2,3,4) # case 1
    b = C_APDU(1,2,3,4,5) # case 2
    c = C_APDU((1,2,3), cla=0x23, data="hallo") # case 3
    d = C_APDU(1,2,3,4,2,4,6,0) # case 4
    
    print
    print a
    print b
    print c
    print d
    print
    print repr(a)
    print repr(b)
    print repr(c)
    print repr(d)
    
    print
    for i in a, b, c, d:
        print hexdump(i.render())
    
    print
    e = R_APDU(0x90,0)
    f = R_APDU("foo\x67\x00")

    print
    print e
    print f
    print
    print repr(e)
    print repr(f)

    print
    for i in e, f:
        print hexdump(i.render())
