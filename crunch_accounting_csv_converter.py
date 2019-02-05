#!/usr/bin/env python
#  coding=utf-8
#  vim:ts=4:sts=4:sw=4:et
#
#  Author: Hari Sekhon
#  Date: 2019-02-04 23:24:30 +0000 (Mon, 04 Feb 2019)
#
#  https://github.com/harisekhon/pytools
#
#  License: see accompanying Hari Sekhon LICENSE file
#
#  If you're using my code you're welcome to connect with me on LinkedIn
#  and optionally send me feedback to help steer this or other code I publish
#
#  https://www.linkedin.com/in/harisekhon
#

"""

Tool to convert Credit Card CSVs with headers to Crunch Accounting standard format - extracts the important fields,
calculates the running balance if necessary

File arguments are read one by one and converted and output to a file of the same name with _crunch.csv at the end

If there is no balance column you must provide a --starting-balance from which to calculate the running balance column
for Crunch, In that case if specifying multiple CSV statements as arguments, they must be given in chronological order
in order for one statement's running balance to flow on to the next in the correct order

Can be easily extended for other banks CSV formats, as it's just simple matching of the headers, all that is required
is a sample

Tested on Barclaycard Commercial statement CSV exports
(Barclaycard lists entries in reverse chronological order so need to use --credit and --reverse-order)

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import csv
import os
import re
import sys
import tempfile
import traceback
from decimal import Decimal
srcdir = os.path.abspath(os.path.dirname(__file__))
libdir = os.path.join(srcdir, 'pylib')
sys.path.append(libdir)
try:
    # pylint: disable=wrong-import-position
    from harisekhon.utils import log, isChars
    from harisekhon import CLI
except ImportError as _:
    print(traceback.format_exc(), end='')
    sys.exit(4)

__author__ = 'Hari Sekhon'
__version__ = '0.3'


class CrunchAccountingCsvConverter(CLI):

    def __init__(self):
        # Python 2.x
        super(CrunchAccountingCsvConverter, self).__init__()
        # Python 3.x
        # super().__init__()
        self.verbose = 2
        self.running_balance = None
        self.default_timeout = None
        self.credit_card = False
        self.reverse_order = False

    def add_options(self):
        super(CrunchAccountingCsvConverter, self).add_options()
        self.add_opt('-c', '--credit-card', action='store_true',
                     help='Credit Card statements (inverts transactions against running balance)')
        self.add_opt('-r', '--reverse-order', action='store_true',
                     help='Statement entries are in reverse chronological order (eg. Barclaycard)')
        self.add_opt('-s', '--starting-balance', help='Starting Balance (used if no balance column is found')

    def process_options(self):
        super(CrunchAccountingCsvConverter, self).process_options()
        self.credit_card = self.get_opt('credit_card')
        self.reverse_order = self.get_opt('reverse_order')
        self.running_balance = self.get_opt('starting_balance')
        if self.running_balance is not None:
            try:
                self.running_balance = Decimal(self.running_balance)
            except ValueError as _:
                log.error('INVALID starting balance %s, must be in a decimal number: %s', self.running_balance, _)
                sys.exit(1)

    def run(self):
        if not self.args:
            self.usage('no file arguments specified')
        for filename in self.args:
            target_filename = '{}_crunch.csv'.format(re.sub(r'\.csv$', '', filename))
            log.info("converting file '%s' => '%s'", filename, target_filename)
            if not self.convert(filename, target_filename):
                log.error("FAILED to convert filename '%s'", filename)

    def convert(self, filename, target_filename):
        if self.reverse_order:
            filename = self.reverse_contents(filename)
        csvreader = self.get_csvreader(filename)
        if not csvreader:
            return False
        count = 0
        (positions, balance_position) = self.detect_columns(csvreader)
        csvwriter = csv.writer(open(target_filename, 'w'))
        csvwriter.writerow(['Date', 'Description', 'Amount', 'Balance'])
        for row in csvreader:
            count += 1
            if balance_position is not None:
                balance = row[balance_position]
            elif self.running_balance is not None:
                self.update_balance(row[positions['amount']])
                balance = self.running_balance
            else:
                log.error('no balance column found and no running balance given')
                sys.exit(2)
            csvwriter.writerow(
                [
                    row[positions['date']],
                    row[positions['desc']],
                    self.amount(row[positions['amount']]),
                    balance
                ]
                )
        log.info('%s: %s CSV lines processed', os.path.basename(filename), count)
        return True

    def amount(self, amount):
        if self.credit_card:
            return -Decimal(amount)
        return amount

    def update_balance(self, amount):
        if self.credit_card:
            self.running_balance -= Decimal(amount)
        else:
            self.running_balance += Decimal(amount)

    @staticmethod
    def reverse_contents(filename):
        lines = open(filename).readlines()
        lines = [lines[0]] + list(reversed(lines[1:]))
        (_, tmp_filename) = tempfile.mkstemp(text=True)
        filehandle = open(tmp_filename, 'w')
        for line in lines:
            filehandle.write(line)
        return tmp_filename

    def detect_columns(self, csvreader):
        headers = csvreader.next()
        positions = {'date': None, 'desc': None, 'amount': None}
        balance_position = None
        for (position, value) in enumerate(headers):
            if 'Date' in value:
                positions['date'] = position
            elif 'Merchant Name' in value:
                positions['desc'] = position
            elif 'Amount' in value:
                positions['amount'] = position
            elif 'Balance' in value:
                balance_position = position
        for pos in positions:
            if positions[pos] is None:
                log.error('field %s not found', pos)
                return False
        if balance_position is None and self.running_balance is None:
            self.usage('no balance column detected, please specify --starting-balance')
        return (positions, balance_position)

    @staticmethod
    def get_csvreader(filename):
        try:
            filehandle = open(filename)
        except IOError as _:
            log.error(_)
            return None
        filename = os.path.basename(filename)
        try:
            dialect = csv.Sniffer().sniff(filehandle.read(1024))
            # this will raise an Error if invalid
            dialect.strict = True
            filehandle.seek(0)
            csvreader = csv.reader(filehandle, dialect)
        except csv.Error as _:
            log.warning('file %s: %s', filename, _)
            return None
        csvreader = CrunchAccountingCsvConverter.validate_csvreader(csvreader, filename)
        filehandle.seek(0)
        return csvreader

    @staticmethod
    def validate_csvreader(csvreader, filename):
        count = 0
        try:
            # csvreader doesn't seem to generate any errors ever :-(
            # csv module allows entire lines of json/xml/yaml to go in as a single field
            # Adding some invalidations manually
            for field_list in csvreader:
                # list of fields with no separator information
                log.debug("line: %s", field_list)
                # make it fail if there is only a single field on any line
                if len(field_list) < 2:
                    log.error("less than 2 fields detected, aborting conversion of file '%s'", filename)
                    return None
                # it's letting JSON through :-/
                if field_list[0] == '{':
                    log.info('JSON opening braces detected, not a CSV?')
                    return None
                # extra protection along the same lines as anti-json:
                # the first char of field should be alphanumeric, not syntax
                # however instead of isAlnum allow quotes for quoted CSVs to pass validation
                if not isChars(field_list[0][0], 'A-Za-z0-9"'):
                    log.info('non-alphanumeric / quote opening character detected in CSV')
                    return None
                count += 1
        except csv.Error  as _:
            log.warning('file %s, line %s: %s', filename, csvreader.line_num, _)
            return None
        if count == 0:
            log.error('zero lines detected, blank input is not valid CSV')
            return None
        return csvreader


if __name__ == '__main__':
    CrunchAccountingCsvConverter().main()
