from pyspark.sql import DataFrame
from pyspark.sql import functions as f
from pyspark.sql import SparkSession


from pyspark.sql import Window

# dfZipWithIndex helper function
from pyspark.sql.types import LongType, StructField, StructType

from pyspark.sql import DataFrame

class Catalog:
    """Build object catalog of files on s3 dbfs or local storage. 
    Save catalog to Delta Lake table by path or table name"""
    CATALOG_PARTITIONS = 2000

    def is_anon(self):
      return self._anon
    
    def _is_anon(self, path:str):
      if path.startswith("s3://"):
        anon=False
        fs = None
        from botocore.exceptions import NoCredentialsError
        import s3fs
        fs = s3fs.S3FileSystem(anon=anon)
        try: 
          fs.exists(path)
        except NoCredentialsError as e:
          print('error', e, "correcting")
          anon=True
    
        return anon

    def __init__(self, spark, table:str = "hive_metastore.pixels_solacc.object_catalog"):
      """Catalog objects and files, collect metadata and thumbnails. The catalog can be used with multiple object types.
          Parameters:
              spark - Spark context
              table - Delta table that stores the object catalog
      """
      assert spark is not None
      self._spark = spark
      self._table = table
      """Spark and Delta Table options for best performance"""
      self._userOptions = {
        'delta.autoOptimize.optimizeWrite': 'true', 
        'delta.autoOptimize.autoCompact': 'true',
        'delta.targetFileSize': '16mb',
        'spark.sql.execution.arrow.maxRecordsPerBatch': '1000',
        'spark.sql.parquet.columnarReaderBatchSize': '1000',
        'spark.sql.execution.arrow.enabled': 'true',
        'spark.sql.parquet.enableVectorizedReader': 'false',
        'spark.sql.parquet.compression.codec': 'uncompressed',
        'spark.databricks.delta.optimizeWrite.enabled': False
      }

    def __repr__(self):
      return f'Catalog(spark, table="{self._table}")'
    
    def catalog(self, path:str, pattern:str = "*", recurse:bool = True) -> DataFrame:
        """Perform the catalog action and return a spark dataframe
          Parameters:
              path  - Root location of objects
              pattern - file name pattern
              recurse - True means recurse folder structure
        """
        assert(self._spark is not None)
        assert type(self._spark) == SparkSession
        assert self._spark.version is not None

        self._anon = self._is_anon(path)
        spark = self._spark
        # spark.sparkContext.setJobDescription("test desc 1")
        df = (self._spark.read
            .format("binaryFile")
            .option("pathGlobFilter",      pattern)
            .option("recursiveFileLookup", str(recurse).lower())
            .load(path)
            .drop('content')    
        )
        df = Catalog._with_path_meta(df)
        df = Catalog._dfZipWithIndex(self._spark, df) # add an unique ID
        return (df)

    def load(self, table:str = None) -> DataFrame:
      """
        @return Spark dataframe representing the object Catalog
      """
      return (self._spark.table(self._table if not table else table))
   
    def save(self,
        df:DataFrame, 
        path:str = None,
        table:str = None,
        mode:str ="append", 
        mergeSchema:bool = True, 
        hasBinary:bool = False,
        userMetadata = None,
        userOptions = {}
        ):
        """
          Save Catalog dataframe to Delta table for later fast recall using .load()
        """
        options = {}
        options['mergeSchema'] = mergeSchema

        if None != userMetadata:
          options["userMetadata"] = userMetadata
        if None != path:
          options["path"] = path
        
        options.update(self._userOptions)
        options.update(userOptions)
  
        print(options)
        spark = self._spark
        spark.sparkContext.setJobDescription("Test Desc")
        return (
            df.write
                .format("delta")
                .mode(mode)
                .options(**options)
                .saveAsTable(self._table if not table else table)
        )

    def _with_path_meta(df, basePath:str = 'dbfs:/', inputCol:str = 'path', num_trailing_path_items:int = 5):
        """ break path up into usable information """
        return (            
                df
                .withColumn("relative_path", f.regexp_replace(inputCol, basePath+r"(.*)$",r"$1"))
                .withColumn("local_path", f.regexp_replace(inputCol,r"^dbfs:(.*$)",r"/dbfs$1"))
                .withColumn("extension",f.regexp_replace(inputCol, r".*\.(\w+)$", r"$1"))
                .withColumn("path_tags",
                                f.slice(
                                    f.split(
                                        f.regexp_replace(
                                            "relative_path",
                                            r"([0-9a-zA-Z]+)([\_\.\/\:\@])",
                                            r"$1,"),
                                        ","
                                    ),
                                    -num_trailing_path_items,
                                    num_trailing_path_items
                                )
                            )
                
            )



    def _dfZipWithIndex(df, offset=1, colName="rowId"):
        '''
        Enumerates dataframe rows in native order, like RDD's zipWithIndex, but on a DataFrame and preserves the schema.
    
        :param df: source dataframe
        :param offset: adjustment to row_number()'s index
        :param colName: name of the index column
        '''
      
        windowSpec = Window.orderBy(f.lit('A'))  # Placeholder ordering as we want to keep the original order
        df_with_index = df.withColumn(colName, f.row_number().over(windowSpec) + offset - 1)
        return df_with_index.repartition(Catalog.CATALOG_PARTITIONS)  # Assuming Catalog.CATALOG_PARTITIONS is defined



if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__)+"/../..")
    from mymodule.pixels import Catalog
    c = Catalog()
    #c.catalog("dbfs:/tmp")
