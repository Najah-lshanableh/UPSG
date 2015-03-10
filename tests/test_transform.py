import numpy as np
from os import system
import unittest

from upsg.pipeline import Pipeline
from upsg.export.csv import CSVWrite
from upsg.fetch.csv import CSVRead
from upsg.transform.rename_cols import RenameCols

from utils import path_of_data

outfile_name = path_of_data('_out.csv')

class TestTransform(unittest.TestCase):
    def test_rename_cols(self):
        infile_name = path_of_data('mixed_csv.csv')        
        rename_dict = {'name' : 'designation', 'height' : 'tallness'}

        p = Pipeline()

        csv_read_node = p.add(CSVRead(infile_name))
        trans_node = p.add(RenameCols(rename_dict))
        csv_write_node = p.add(CSVWrite(outfile_name))

        csv_read_node['out'] > trans_node['in']
        trans_node['out'] > csv_write_node['in']

        p.run()

        control = {'id', 'designation', 'tallness'}
        result = set(np.genfromtxt(outfile_name, dtype=None, delimiter=",", 
            names=True).dtype.names)
        
        self.assertTrue(np.array_equal(result, control))


    def tearDown(self):
        system('rm *.upsg')
        system('rm {}'.format(outfile_name))

if __name__ == '__main__':
    unittest.main()