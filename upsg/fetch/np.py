from ..stage import Stage
from ..uobject import UObject, UObjectPhase

from upsg.utils import is_sa, np_nd_to_sa

class NumpyRead(Stage):
    def __init__(self, A):
        self.__A = A
    
    @property
    def input_keys(self):
        return []

    @property
    def output_keys(self):
        return ['out']

    def run(self, outputs_requested, **kwargs):
        uo = UObject(UObjectPhase.Write)
        uo.from_np(self.__A)
        return {'out' : uo}
