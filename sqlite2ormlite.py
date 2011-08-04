#!/bin/python

import os
import sys
import sqlite3

def underscoreToCamelcase(value, capitalize_first_word=True):
    output = ""
    seen_first = False
    for word in value.split('_'):
        if not word:
            continue
        else:
            if not seen_first:
                if capitalize_first_word:
                    nextWord = word.capitalize()
                else:
                    nextWord = word
                seen_first = True
            else:
                nextWord = word.capitalize()
            output += nextWord

    return output

def singularize(word):
    sing_rules = [lambda w: w[-3:] == 'ies' and w[:-3] + 'y',
                  lambda w: w[-4:] == 'ives' and w[:-4] + 'ife',
                  lambda w: w[-3:] == 'ves' and w[:-3] + 'f',
                  lambda w: w[-3:] == 'tes' and w[:-1],
                  lambda w: w[-3:] == 'ces' and w[:-1],
                  lambda w: w[-2:] == 'es' and w[:-2],
                  lambda w: w[-1:] == 's' and w[:-1],
                  lambda w: w,
                  ]
    word = word.strip()
    singleword = [f(word) for f in sing_rules if f(word) is not False][0]
    return singleword

javaTypes = {
    'text': "String",
    'integer': "Integer",
    'integer PKEY': "Integer",
    'real': "Double",
}
ormliteTypes = {
    'text': "STRING",
    'integer': "INTEGER_OBJ",
    'integer PKEY': "INTEGER_OBJ",
    'real': "DOUBLE_OBJ",
}

if len(sys.argv) < 4:
    print "%s <sqlite3 db name>[:table name[,table name...]] <java src directory> <java package name>"
    sys.exit(1)

dbinfo = sys.argv[1].split(':')
if len(dbinfo) == 1:
    dbname = dbinfo[0]
    tables = "*"
else:
    (dbname, tables) = dbinfo
srcDir = sys.argv[2]
packageName = sys.argv[3]

if not os.path.exists(dbname):
    print "Database %s does not exist." % (dbname)
    sys.exit(1)

print "Database name: ", dbname
print "Tables: ", tables
print "Src dir: ", srcDir
print "Package name: ", packageName

# Get table names
tableNames = []
conn = sqlite3.connect(dbname)
c = conn.cursor()
c.execute('SELECT name FROM sqlite_master WHERE type="table"');
for row in c:
    if tables == '*' or row[0] in tables:
        tableNames.append(row[0])

print "Accepted tables: ", ', '.join(tableNames)

rootPath = "%s/%s/" % (srcDir, packageName.replace('.', '/'))

# Parse the database schema into memory
classes = {}
for table in tableNames:
    className = underscoreToCamelcase(str(table))
    className = singularize(className)

    fileName = rootPath + className + ".java"

    clazz = {
        'java_class_name': className,
        'java_file_name': fileName,
        'columns': {}
    }
    
    c.execute('PRAGMA table_info("%s")' % (table))
    for row in c:
        clazz['columns'][row[1]] = {
            'java_type': javaTypes[row[2]],
            'java_column_const': 'COLUMN_' + row[1].upper(),
            'ormlite_type': ormliteTypes[row[2]],
            'member_name': underscoreToCamelcase(row[1], False),
            'getter_name': 'get' + underscoreToCamelcase(row[1], True),
            'is_key': (True if row[2][-5:] == ' PKEY' else False),
            'not_null': bool(row[3]),
            'order': int(row[0]), # So I don't have to use an OrderedDict
        }

    classes[table] = clazz

# Look for foreign fields using <column_name>_id
for (fromTableName, fromTable) in classes.items():
    for (fromColumnName, fromCol) in fromTable['columns'].items():
        if len(fromColumnName) > 4 and fromColumnName[-4:] == 's_id':
            toTableName = fromColumnName[:-3]
            print "Found foreign relationship from %s to %s." % (fromTableName, toTableName)
            if toTableName in classes:
                toTable = classes[toTableName]
                toTable['requires_foreign_imports'] = True
                memberName = underscoreToCamelcase(fromTableName, False)
                getterName = 'get' + underscoreToCamelcase(fromTableName, True)
                print "Creating field %s in class %s." % (fromTableName, toTable['java_class_name'])
                toTable['columns'][fromTableName] = {
                    'not_null': False,
                    'member_name': memberName,
                    'getter_name': getterName,
                    'foreign': True,
                    'java_type': 'ForeignCollection<%s>' % (fromTable['java_class_name']),
                    'order': 99999,
                }


# Output to Java files
for (table, clazz) in classes.items():
    fileName = clazz['java_file_name']
    className = clazz['java_class_name']
    type_data = sorted(clazz['columns'].items(), lambda x, y: cmp(x[1]['order'], y[1]['order']))
    print "Creating ", fileName

    f = open(fileName, 'w')

    f.write('package %s;\n' % (packageName))

    f.write('\n')
    f.write('import com.j256.ormlite.field.DataType;\n')
    f.write('import com.j256.ormlite.field.DatabaseField;\n')
    f.write('import com.j256.ormlite.table.DatabaseTable;\n')
    if 'requires_foreign_imports' in clazz:
        f.write('import com.j256.ormlite.dao.ForeignCollection;\n')
        f.write('import com.j256.ormlite.field.ForeignCollectionField;\n')
    f.write('\n')

    f.write('@DatabaseTable(tableName = "%s")\n' % (table))
    
    f.write('public class %s {\n' % (className))

    f.write('\n')

    # Generate COLUMN_* constants to help with querying
    #for (column_name, data) in type_data.items():
    for (column_name, data) in type_data:
        if 'java_column_const' in data:
            f.write('    ')
            f.write('public static final String %s = "%s";\n' % (data['java_column_const'],
                                                                 column_name))
    f.write('\n')

    # Generate types
    for (column_name, data) in type_data:
        f.write('    ')
        if 'foreign' in data:
            f.write('@ForeignCollectionField\n')
        else:
            f.write('@DatabaseField(dataType = DataType.')
            f.write(data['ormlite_type'])
            if data['not_null'] == True:
                f.write(', canBeNull = false')
            f.write(', columnName = ')
            f.write(data['java_column_const'])
            f.write(')\n')

        f.write('    ')
        f.write('private %s %s;\n' % (data['java_type'],
                                      data['member_name']))

        f.write('\n')

    # Generate required no-arg constructor
    f.write('    ')
    f.write(className)
    f.write('() { /* Empty constructor for ORMlite */ }\n')
    f.write('\n')

    for (column_name, data) in type_data:
        f.write('    public %s %s() {\n' % (data['java_type'], data['getter_name']))
        f.write('        return %s;\n' % (data['member_name']))
        f.write('    }\n');

        f.write('\n')
    
    f.write('}')

    f.close()

conn.close()

