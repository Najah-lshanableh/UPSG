import ast
import numpy as np
from os import system
import unittest

from numpy.lib.recfunctions import append_fields

from sklearn.cross_validation import KFold as SKKFold

from upsg.pipeline import Pipeline
from upsg.export.csv import CSVWrite
from upsg.export.np import NumpyWrite
from upsg.fetch.csv import CSVRead
from upsg.fetch.np import NumpyRead
from upsg.transform.rename_cols import RenameCols
from upsg.transform.sql import RunSQL
from upsg.transform.split import Query, SplitColumns, KFold
from upsg.transform.fill_na import FillNA
from upsg.transform.label_encode import LabelEncode
from upsg.transform.lambda_stage import LambdaStage
from upsg.transform.timify import Timify
from upsg.utils import np_nd_to_sa, np_sa_to_nd, is_sa

from utils import path_of_data, UPSGTestCase, csv_read


class TestTransform(UPSGTestCase):

    def test_rename_cols(self):
        infile_name = path_of_data('mixed_csv.csv')
        rename_dict = {'name': 'designation', 'height': 'tallness'}

        p = Pipeline()

        csv_read_node = p.add(CSVRead(infile_name))
        trans_node = p.add(RenameCols(rename_dict))
        csv_write_node = p.add(CSVWrite(self._tmp_files('out.csv')))

        csv_read_node['out'] > trans_node['in']
        trans_node['out'] > csv_write_node['in']

        p.run()

        control = {'id', 'designation', 'tallness'}
        result = set(self._tmp_files.csv_read('out.csv').dtype.names)

        self.assertTrue(np.array_equal(result, control))

    def test_sql(self):

        # Make sure we don't accidentally corrupt our test database
        db_path, db_file_name = self._tmp_files.tmp_copy(path_of_data(
            'small.db'))
        db_url = 'sqlite:///{}'.format(db_path)
        
        q_sel_employees = 'CREATE TABLE {tmp_emp} AS SELECT * FROM employees;'
        # We have to be careful about the datetime type in sqlite3. It will
        # forget if we don't keep reminding it, and if it forgets sqlalchemy
        # will be unhappy. Hence, we can't use CREATE TABLE AS if our table
        # has a DATETIME
        q_sel_hours = ('CREATE TABLE {tmp_hrs} '
                       '(id INT, employee_id INT, time DATETIME, '
                       '    event_type TEXT); '
                       'INSERT INTO {tmp_hrs} SELECT * FROM hours;')
        q_join = ('CREATE TABLE {joined} '
                  '(id INT, last_name TEXT, salary REAL, time DATETIME, '
                  '    event_type TEXT); '
                  'INSERT INTO {joined} '
                  'SELECT {tmp_emp}.id, last_name, salary, time, event_type '
                  'FROM {tmp_emp} JOIN {tmp_hrs} ON '
                  '{tmp_emp}.id = {tmp_hrs}.employee_id;')

        p = Pipeline()
        get_emp = p.add(RunSQL(db_url, q_sel_employees, [], ['tmp_emp'], {}))
        get_hrs = p.add(RunSQL(db_url, q_sel_hours, [], ['tmp_hrs'], {}))
        join = p.add(RunSQL(db_url, q_join, ['tmp_emp', 'tmp_hrs'], ['joined'],
                            {}))
        csv_out = p.add(CSVWrite(self._tmp_files('out.csv')))

        get_emp['tmp_emp'] > join['tmp_emp']
        get_hrs['tmp_hrs'] > join['tmp_hrs']
        join['joined'] > csv_out['in']

        p.run()

        result = self._tmp_files.csv_read('out.csv')
        ctrl = csv_read(path_of_data('test_transform_test_sql_ctrl.csv'))

        self.assertTrue(np.array_equal(result, ctrl))

    def test_split_columns(self):

        p = Pipeline()

        csv_in = p.add(CSVRead(path_of_data('numbers.csv')))
        split = p.add(SplitColumns(('F1', 'F3')))
        csv_out_sel = p.add(CSVWrite(self._tmp_files('out_sel.csv')))
        csv_out_rest = p.add(CSVWrite(self._tmp_files('out_rest.csv')))

        csv_in['out'] > split['in']
        split['selected'] > csv_out_sel['in']
        split['rest'] > csv_out_rest['in']

        p.run()
        
        result = self._tmp_files.csv_read('out_sel.csv')
        ctrl = csv_read(path_of_data('test_split_columns_ctrl_selected.csv'))

        self.assertTrue(np.array_equal(result, ctrl))

        result = self._tmp_files.csv_read('out_rest.csv')
        ctrl = csv_read(path_of_data('test_split_columns_ctrl_rest.csv'))

        self.assertTrue(np.array_equal(result, ctrl))

    def __test_ast_trans(self, raw, target, col_names):    
        # There doesn't seem to be a better easy way to test AST equality
        # than seeing if their dumps are equal:
        # http://stackoverflow.com/questions/3312989/elegant-way-to-test-python-asts-for-equality-not-reference-or-object-identity
        # If it gets to be a problem, we'll hand-roll something
        q = Query(raw)
        ctrl = ast.dump(ast.parse(target, mode='eval'))
        result = q.dump_ast(col_names)
        self.assertEqual(result, ctrl)

    def test_query(self):
        # Make sure we can support simple queries
        ast_tests = [("id < 10", 
                      "in_table['id'] < 10", 
                      ('id', 'name')),
                     ("name == 'Bruce'", 
                      "in_table['name'] == 'Bruce'",
                      ('id', 'name')),
                     ("(id < 10) or (name == 'Bruce' and hired_dt != stop_dt)",
                      ("np.logical_or("
                           "in_table['id'] < 10, "
                           "np.logical_and("
                               "in_table['name'] == 'Bruce', "
                               "in_table['hired_dt'] != in_table['stop_dt']))"),
                      ('id', 'name', 'hired_dt', 'stop_dt')),
                     ("id >= 5 and not (terminated or not salary < 10000)",
                      ("np.logical_and("
                           "in_table['id'] >= 5, "
                           "np.logical_not("
                               "np.logical_or("
                                   "in_table['terminated'], "
                                   "np.logical_not("
                                        "in_table['salary'] < 10000))))"),
                      ('id', 'terminated', 'salary', 'demerits'))]
        for raw, target, col_names in ast_tests:
            self.__test_ast_trans(raw, target, col_names)

        p = Pipeline()

        # NEXT redesign this test so it has an or in it
        csv_in = p.add(CSVRead(path_of_data('query.csv')))
        q1_node = p.add(Query("((id == value) and not (use_this_col == 'no'))"
                              "or name == 'fish'"))
        csv_out = p.add(CSVWrite(self._tmp_files('out.csv')))
        csv_comp = p.add(CSVWrite(self._tmp_files('out_comp.csv')))

        csv_in['out'] > q1_node['in']
        q1_node['out'] > csv_out['in']
        q1_node['complement'] > csv_comp['in']

        p.run()

        result = self._tmp_files.csv_read('out.csv')
        ctrl = csv_read(path_of_data('query_ctrl.csv'))

        self.assertTrue(np.array_equal(result, ctrl))

        result = self._tmp_files.csv_read('out_comp.csv')
        ctrl = csv_read(path_of_data('query_ctrl_comp.csv'))

        self.assertTrue(np.array_equal(result, ctrl))

    def test_fill_na(self):

        p = Pipeline()

        csv_in = p.add(CSVRead(path_of_data('missing_vals_mixed.csv')))
        fill_na = p.add(FillNA(-1))
        csv_out = p.add(CSVWrite(self._tmp_files('out.csv')))

        csv_in['out'] > fill_na['in']
        fill_na['out'] > csv_out['in']

        p.run()

        result = self._tmp_files.csv_read('out.csv')
        ctrl = csv_read(path_of_data('test_transform_test_fill_na_ctrl.csv'))
        
        self.assertTrue(np.array_equal(result, ctrl))

    def test_label_encode(self):

        p = Pipeline()

        csv_in = p.add(CSVRead(path_of_data('categories.csv')))
        le = p.add(LabelEncode())
        csv_out = p.add(CSVWrite(self._tmp_files('out.csv')))

        csv_in['out'] > le['in']
        le['out'] > csv_out['in']

        p.run()

        result = self._tmp_files.csv_read('out.csv')
        ctrl = csv_read(path_of_data('test_transform_test_label_encode_ctrl.csv'))
        
        self.assertTrue(np.array_equal(result, ctrl))

    def test_kfold(self):

        folds = 3
        rows = 6

        X = np.random.randint(0, 1000, (rows, 3))
        y = np.random.randint(0, 1000, (rows, 1))

        p = Pipeline()

        np_in_X = p.add(NumpyRead(X))
        np_in_y = p.add(NumpyRead(y))

        kfold = p.add(KFold(2, folds, random_state=0))
        np_in_X['out'] > kfold['in0']
        np_in_y['out'] > kfold['in1']

        ctrl_kf = SKKFold(rows, n_folds = folds, random_state=0)
        out_files = []
        expected_folds = []
        arrays = (X, y)
        for fold_i, train_test_inds in enumerate(ctrl_kf):
            for array_i, array in enumerate(arrays):
                for select_i, selection in enumerate(('train', 'test')):
                    out_key = '{}{}_{}'.format(selection, array_i, fold_i) 
                    out_file = out_key + '.csv'
                    out_files.append(out_file)
                    stage = p.add(CSVWrite(self._tmp_files(out_file)))
                    kfold[out_key] > stage['in']
                    slice_inds = train_test_inds[select_i]
                    expected_folds.append(
                            np_nd_to_sa(arrays[array_i][slice_inds]))

        p.run()

        for out_file, expected_fold in zip(out_files, expected_folds):
            self.assertTrue(np.array_equal(
                self._tmp_files.csv_read(out_file),
                expected_fold))

    def test_lambda(self):

        in_data = np_nd_to_sa(np.random.random((100, 10)))
        scale = np_nd_to_sa(np.array(3))
        out_keys = ['augmented', 'log_col', 'sqrt_col', 'scale_col'] 

        def log1_sqrt2_scale3(A, scale):
            names = A.dtype.names
            log_col = np.log(A[names[0]])
            sqrt_col = np.sqrt(A[names[1]])
            scale_col = A[names[2]] * scale[0][0]

            return (append_fields(
                        A, 
                        ['log1', 'sqrt2', 'scale3'], 
                        (log_col, sqrt_col, scale_col)),
                    log_col,
                    sqrt_col,
                    scale_col)

        p = Pipeline()

        np_in = p.add(NumpyRead(in_data))
        scale_in = p.add(NumpyRead(scale))

        lambda_stage = p.add(
            LambdaStage(
                log1_sqrt2_scale3, 
                out_keys))
        np_in['out'] > lambda_stage['A']
        scale_in['out'] > lambda_stage['scale']

        csv_out_stages = []
        for key in out_keys:
            stage = p.add(
                    CSVWrite(
                        self._tmp_files(
                            'out_{}.csv'.format(key))))
            csv_out_stages.append(stage)
            lambda_stage[key] > stage['in']

        p.run()

        controls = log1_sqrt2_scale3(in_data, scale)

        for i, key in enumerate(out_keys):
            control = controls[i]
            if is_sa(control):
                control = np_sa_to_nd(control)[0]
            result = self._tmp_files.csv_read(
                        'out_{}.csv'.format(key), 
                        as_nd=True)
            self.assertTrue(np.allclose(control, result))

    def test_timify(self):
        in_file = path_of_data('with_dates.csv')

        p = Pipeline()

        csv_in = p.add(CSVRead(in_file))

        timify = p.add(Timify())
        csv_in['out'] > timify['in']

        np_out = p.add(NumpyWrite())
        timify['out'] > np_out['in']

        p.run()
        result = np_out.get_stage().result

        ctrl_raw = csv_read(in_file)
        ctrl_dtype = np.dtype([(name, '<M8[D]') if 'dt' in name else 
                               (name, fmt) for name, fmt in 
                               ctrl_raw.dtype.descr])
        ctrl_better = csv_read(in_file, dtype=ctrl_dtype)

        self.assertEqual(result.dtype, ctrl_better.dtype)
        self.assertTrue(np.array_equal(result, ctrl_better))

if __name__ == '__main__':
    unittest.main()
