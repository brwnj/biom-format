#!/usr/bin/env python

from __future__ import division
from biom.table import DenseOTUTable, SparseOTUTable, table_factory, \
        to_sparsedict
import json
from numpy import zeros, asarray
from string import strip

__author__ = "Justin Kuczynski"
__copyright__ = "Copyright 2012, BIOM-Format Project"
__credits__ = ["Justin Kuczynski", "Daniel McDonald", "Greg Caporaso"]
__license__ = "GPL"
__url__ = "http://biom-format.org"
__version__ = "0.9dev"
__maintainer__ = "Daniel McDonald"
__email__ = "daniel.mcdonald@colorado.edu"
__status__ = "Development"

MATRIX_ELEMENT_TYPE = {'int':int,'float':float,'str':str,
                       u'int':int,u'float':float,u'str':str}

def parse_biom_table(json_fh,constructor=None):
    """parses a biom format otu table into a rich otu table object

    input is an open filehandle or compatable object (e.g. list of lines)

    sparse/dense will be determined by "matrix_type" in biom file, and 
    either a SparseOTUTable or DenseOTUTable object will be returned
    note that sparse here refers to the compressed format of [row,col,count]
    dense refers to the full / standard matrix representations
    """
    return parse_biom_table_str(''.join(json_fh),constructor=constructor)

def parse_biom_otu_table(json_table, constructor=None):
    """Parse a biom otu table type

    Constructor must have a _biom_type of "otu table"
    """
    if constructor is None:
        if json_table['matrix_type'].lower() == 'sparse':
            constructor = SparseOTUTable
        elif json_table['matrix_type'].lower() == 'dense':
            constructor = DenseOTUTable
        else:
            raise ValueError, "Unknown matrix_type"
    else:
        if constructor._biom_type.lower() != 'otu table':
            raise ValueError, "constructor must subclass OTUTable"

    sample_ids = [col['id'] for col in json_table['columns']]
    # null metadata -> None object in metadata list 
    sample_metadata = [col['metadata'] for col in json_table['columns']]
    obs_ids = [row['id'] for row in json_table['rows']]
    obs_metadata = [row['metadata'] for row in json_table['rows']]

    table_obj = table_factory(json_table['data'], sample_ids, obs_ids, 
                              sample_metadata, obs_metadata, 
                              constructor=constructor)

    return table_obj

# map table types -> parsing methods
BIOM_TYPES = {'otu table':parse_biom_otu_table}
def parse_biom_table_str(json_str,constructor=None):
    """Parses a JSON string of the Biom table into a rich table object.
   
    If constructor is none, the constructor is determined based on BIOM
    information
    """
    json_table = json.loads(json_str)

    if constructor is None:
        f = BIOM_TYPES.get(json_table['type'].lower(), None)
    else:
        f = BIOM_TYPES.get(constructor._biom_type.lower(), None)

        # convert matrix data if the biom type doesn't match matrix type
        # of the table objects
        if constructor._biom_matrix_type != json_table['matrix_type'].lower():
            if json_table['matrix_type'] == 'dense':
                # dense -> sparse
                conv_data = []
                for row_idx,row in enumerate(json_table['data']):
                    for col_idx, value in enumerate(row):
                        if value == 0:
                            continue
                        conv_data.append([row_idx,col_idx,value])
                json_table['data'] = conv_data

            elif json_table['matrix_type'] == 'sparse':
                # sparse -> dense
                conv_data = zeros(json_table['shape'],dtype=float)
                for r,c,v in json_table['data']:
                    conv_data[r,c] = v
                json_table['data'] = [list(row) for row in conv_data]

            else:
                raise ValueError, "Unknown matrix_type"

    if f is None:
        raise ValueError, 'Unknown table type'

    return f(json_table, constructor)

def parse_classic_table_to_rich_table(lines, sample_mapping, obs_mapping, 
        constructor, **kwargs):
    """Parses an table (tab delimited) (observation x sample)

    sample_mapping : can be None or {'sample_id':something}
    obs_mapping : can be none or {'observation_id':something}
    """
    sample_ids, obs_ids, data, t_md, t_md_name = parse_classic_table(lines, 
                                                        **kwargs)

    # if we have it, keep it
    if t_md is None:
        obs_metadata = None
    else:
        obs_metadata = [{t_md_name:v} for v in t_md]

    if sample_mapping is None:
        sample_metadata = None
    else:
        sample_metadata = [sample_mapping[sample_id] for sample_id in sample_ids]

    # will override any metadata from parsed table
    if obs_mapping is not None:
        obs_metadata = [obs_mapping[obs_id] for obs_id in obs_ids]

    if constructor._biom_matrix_type == 'sparse':
        data = nparray_to_sparsedict(data)
    
    return table_factory(data, sample_ids, obs_ids, sample_metadata, 
                         obs_metadata, constructor=constructor)

def parse_classic_table(lines, delim='\t', dtype=float, header_mark=None, \
        md_parse=None):
    """Parse a classic table into (sample_ids, obs_ids, data, metadata, md_name)

    If the last column does not appear to be numeric, interpret it as 
    observation metadata, otherwise None.

    md_name is the column name for the last column if non-numeric

    NOTE: this is intended to be close to how QIIME classic OTU tables are
    parsed with the exception of the additional md_name field
    """
    if not isinstance(lines, list):
        try:
            lines = lines.readlines()
        except AttributeError:
            raise ValueError, "Input needs to support readlines or be indexable"

    # find header, the first line that is not empty and does not start with a #
    for idx,l in enumerate(lines):
        if not l.strip():
            continue
        if not l.startswith('#'):
            break
        if header_mark and l.startswith(header_mark):
            break

    if idx == 0:
        data_start = 1
        header = lines[0].strip().split(delim)[1:]
    else:
        if header_mark is not None:
            data_start = idx + 1
            header = lines[idx].strip().split(delim)[1:]
        else:
            data_start = idx
            header = lines[idx-1].strip().split(delim)[1:]

    # attempt to determine if the last column is non-numeric, ie, metadata
    first_values = lines[data_start].strip().split(delim)
    last_value = first_values[-1]
    last_column_is_numeric = True

    if '.' in last_value:
        try:
            float(last_value)
        except ValueError:
            last_column_is_numeric = False
    else:
        try:
            int(last_value)
        except ValueError:
            last_column_is_numeric = False
    
    # determine sample ids
    if last_column_is_numeric:
        md_name = None
        metadata = None
        samp_ids = header[:]
    else:
        md_name = header[-1]
        metadata = []
        samp_ids = header[:-1]
    
    data = []
    obs_ids = []
    for line in lines[data_start:]:
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue

        fields = line.strip().split(delim)
        obs_ids.append(fields[0])

        if last_column_is_numeric:
            values = map(dtype, fields[1:])
        else:
            values = map(dtype, fields[1:-1])

            if md_parse is not None:
                metadata.append(md_parse(fields[-1]))
            else:
                metadata.append(fields[-1])

        data.append(values)

    return samp_ids, obs_ids, asarray(data), metadata, md_name

def generatedby():
    """Returns a generated by string"""
    return 'BIOM-Format %s' % __version__

def convert_table_to_biom(table_f,sample_mapping, obs_mapping, constructor, 
        **kwargs):
    """Convert a contigency table to a biom table
    
    sample_mapping : dict of {'sample_id':metadata} or None
    obs_mapping : dict of {'obs_id':metadata} or None
    constructor : a biom table type
    dtype : type of table data
    """
    otu_table = parse_classic_table_to_rich_table(table_f, sample_mapping, 
                                                  obs_mapping, constructor, 
                                                  **kwargs)
    return otu_table.getBiomFormatJsonString(generatedby())

def convert_biom_to_table(biom_f, header_key=None, header_value=None, \
        md_format=None):
    """Convert a biom table to a contigency table"""
    table = parse_biom_table(biom_f)
    if table.ObservationMetadata is None:
        return table.delimitedSelf()
    
    if header_key in table.ObservationMetadata[0]:
        return table.delimitedSelf(header_key=header_key, 
                                       header_value=header_value,
                                       metadata_formatter=md_format)
    else:
        return table.delimitedSelf()