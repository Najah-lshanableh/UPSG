import numpy as np

from ..stage import RunnableStage
from ..uobject import UObject, UObjectPhase
from ..utils import np_sa_to_nd


class FillNA(RunnableStage):

    """Fills NaNs with some default value"""

    def __init__(self, default_value):
        """

        parameters
        ----------
        default_value: number

        """
        self.__default_value = default_value

    @property
    def input_keys(self):
        return ['in']

    @property
    def output_keys(self):
        return ['out']

    def run(self, outputs_requested, **kwargs):
        # TODO maybe we can avoid rewriting all the data (esp in sql) by
        # creating some sort of a "view" object
        default_value = self.__default_value
        uo_out = UObject(UObjectPhase.Write)
        in_array = kwargs['in'].to_np()
        col_names = in_array.dtype.names
        # http://stackoverflow.com/questions/5124376/convert-nan-value-to-zero
        for col_name in col_names:
            in_array[col_name][np.isnan(in_array[col_name])] = default_value 
        uo_out.from_np(in_array)

        return {'out': uo_out}