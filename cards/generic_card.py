import crypto_utils, utils, pycsc, binascii, fnmatch
from utils import C_APDU, R_APDU

DEBUG = True
#DEBUG = False

class Card:
    APDU_GET_RESPONSE = C_APDU("\x00\xC0\x00\x00")
    APDU_VERIFY_PIN = C_APDU("\x00\x20\x00\x00")
    SW_OK = '\x90\x00'
    ATRS = []
    DRIVER_NAME = "Generic"
    ## Note: a key in this dictionary may either be a two-byte string containing
    ## a binary status word, or a four-byte string containing a hexadecimal
    ## status word, possibly with ? characters marking variable nibbles. 
    ## Hexadecimal characters MUST be in uppercase. The values that four-byte
    ## strings map to may be either format strings, that can make use of the 
    ## keyword substitutions for SW1 and SW2 or a callable accepting two arguments 
    ## (SW1, SW2) that returns a string.
    STATUS_WORDS = { 
        SW_OK: "Normal execution",
        '61??': "%(SW2)i (0x%(SW2)02x) bytes of response data can be retrieved with GetResponse.",
        '6C??': "Bad value for LE, 0x%(SW2)02x is the correct value.",
        '63C?': lambda SW1,SW2: "The counter has reached the value '%i'" % (SW2%16)
    }

    def __init__(self, card = None, reader = None):
        if card is None:
            if reader is None:
                self.card = pycsc.pycsc(protocol = pycsc.SCARD_PROTOCOL_ANY)
            else:
                self.card = pycsc.pycsc(protocol = pycsc.SCARD_PROTOCOL_ANY, reader = reader)
        else:
            self.card = card
        
        self._i = 0
        self.last_apdu = None
        self.last_sw = None
        self.last_result = None
        self.sw_changed = False
    
    def verify_pin(self, pin_number, pin_value):
        apdu = C_APDU(self.APDU_VERIFY_PIN, P2 = pin_number,
            data = pin_value)
        result = self.send_apdu(apdu)
        return result.sw == self.SW_OK
    
    def cmd_verify(self, pin_number, pin_value):
        """Verify a PIN."""
        pin_number = int(pin_number, 0)
        pin_value = binascii.a2b_hex("".join(pin_value.split()))
        self.verify_pin(pin_number, pin_value)
    
    def cmd_reset(self):
        """Reset the card."""
        self.card.reconnect(init=pycsc.SCARD_RESET_CARD)
    
    COMMANDS = {
        "reset": cmd_reset,
        "verify": cmd_verify
    }

    def _real_send(self, apdu):
        apdu_binary = apdu.render()
        
        if DEBUG:
            print ">> " + utils.hexdump(apdu_binary, indent = 3)
        
        result_binary = self.card.transmit(apdu_binary)
        result = R_APDU(result_binary)
        
        self.last_apdu = apdu
        self.last_sw = result.sw
        self.sw_changed = True
        
        if DEBUG:
            print "<< " + utils.hexdump(result_binary, indent = 3)
        return result
    
    def send_apdu(self, apdu):
        if DEBUG:
            print "%s\nBeginning transaction %i" % ('-'*80, self._i)
        
        if hasattr(self, "before_send"):
            apdu = self.before_send(apdu)
        
        result = self._real_send(apdu)
        
        if result.sw1 == 0x61:
            ## Need to call GetResponse
            gr_apdu = C_APDU(self.APDU_GET_RESPONSE, le = result.sw2) # FIXME
            result = R_APDU(self._real_send(gr_apdu))
        
        if DEBUG:
            print "Ending transaction %i\n%s\n" % (self._i, '-'*80)
        self._i = self._i + 1
        
        self.last_result = result
        return result
    
    def can_handle(cls, card):
        """Determine whether this class can handle a given pycsc object."""
        ATR = card.status().get("ATR","")
        for (knownatr, mask) in cls.ATRS:
            if len(knownatr) != len(ATR):
                continue
            if crypto_utils.andstring(knownatr, mask) == crypto_utils.andstring(ATR, mask):
                return True
        return False
    can_handle = classmethod(can_handle)
    
    def get_prompt(self):
        return "(%s)" % self.DRIVER_NAME
    
    def decode_statusword(self):
        if self.last_sw is None:
            return "No command executed so far"
        else:
            retval = None
            
            desc = self.STATUS_WORDS.get(self.last_sw)
            if desc is not None:
                retval = desc
            else:
                target = binascii.b2a_hex(self.last_sw).upper()
                for (key, value) in self.STATUS_WORDS.items():
                    if fnmatch.fnmatch(target, key):
                        if isinstance(value, str):
                            retval = value % { "SW1": ord(self.last_sw[0]), 
                                "SW2": ord(self.last_sw[1]) }
                            break
                            
                        elif callable(value):
                            retval = value( ord(self.last_sw[0]),
                                ord(self.last_sw[1]) )
                            break
        
        if retval is None:
            return "Unknown SW (SW %s)" % binascii.b2a_hex(self.last_sw)
        else:
            return "%s (SW %s)" % (retval, binascii.b2a_hex(self.last_sw))
    
    def get_protocol(self):
        return ((self.card.status()["Protocol"] == pycsc.SCARD_PROTOCOL_T0) and (0,) or (1,))[0]
