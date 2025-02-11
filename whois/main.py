#!/usr/bin/python3

import os
import re
import getopt
import sys
import json

from typing import (
    Optional,
    Tuple,
    Any,
    List,
    Dict,
)

import whois  # to be compatible with dannycork

# import whoisdomain as whois  # to be compatible with dannycork

# if we are not running as test2.py run in a simplistic way
SIMPLISTIC: bool = False
WithRedacted: bool = False

PrintJson: bool = False
Verbose: bool = False
PrintGetRawWhoisResult: bool = False
Ruleset: bool = False

Failures: Dict[str, Any] = {}
IgnoreReturncode: bool = False


class ResponseCleaner:
    data: str
    rDict: Dict[str, Any] = {}

    def __init__(
        self,
        pathToTestFile: str,
    ):
        self.data = self.readInputFile(pathToTestFile)

    def readInputFile(
        self,
        pathToTestFile: str,
    ) -> str:
        if not os.path.exists(pathToTestFile):
            return ""

        with open(pathToTestFile, mode="rb") as f:  # switch to binary mode as that is what Popen uses
            # make sure the data is treated exactly the same as the output of Popen
            return f.read().decode(errors="ignore")

    def cleanSection(
        self,
        section: List[str],
    ) -> List[str]:
        # cleanup any beginning and ending empty lines from the section

        if len(section) == 0:
            return section

        rr = r"^\s*$"
        n = 0  # remove empty lines from the start of section
        while re.match(rr, section[n]):
            section.pop(n)
            # n stays 0

        n = len(section) - 1  # remove empty lines from the end of the section
        while re.match(rr, section[n]):
            section.pop(n)
            n = len(section) - 1  # remove empty lines from the end of section

        return section

    def splitBodyInSections(
        self,
        body: List[str],
    ) -> List[str]:
        # split the body on empty line, cleanup all sections, remove empty sections
        # return list of body's

        sections: List[List[str]] = []
        n = 0
        sections.append([])
        for line in body:
            if re.match(r"^\s*$", line):
                n += 1
                sections.append([])
                continue
            sections[n].append(line)

        m = 0
        while m < len(sections):
            sections[m] = self.cleanSection(sections[m])
            m += 1

        # now remove empty sections and return
        sections2: List[str] = []
        m = 0
        while m < len(sections):
            if len(sections[m]) > 0:
                sections2.append("\n".join(sections[m]))
            m += 1

        return sections2

    def cleanupWhoisResponse(
        self,
        verbose: bool = False,
        with_cleanup_results: bool = False,
    ) -> Tuple[str, Dict[Any, Any]]:
        result = whois.cleanupWhoisResponse(
            self.data,
            verbose,
            with_cleanup_results,
        )

        self.rDict: Dict[str, Any] = {
            "BodyHasSections": False,  # if this is true the body is not a list of lines but a list of sections with lines
            "Preamble": [],  # the lines telling what whois servers wwere contacted
            "Percent": [],  # lines staring with %% , often not present but may contain hints
            "Body": [],  # the body of the whois, may be in sections separated by empty lines
            "Postamble": [],  # copyright and other not relevant info for actual parsing whois
        }
        body: List[str] = []

        rr: List[str] = []
        z = result.split("\n")
        preambleSeen = False
        postambleSeen = False
        percentSeen = False
        for line in z:
            if preambleSeen is False:
                if line.startswith("["):
                    self.rDict["Preamble"].append(line)
                    line = "PRE;" + line
                    continue
                else:
                    preambleSeen = True

            if preambleSeen is True and percentSeen is False:
                if line.startswith("%"):
                    self.rDict["Percent"].append(line)
                    line = "PERCENT;" + line
                    continue
                else:
                    percentSeen = True

            if postambleSeen is False:
                if line.startswith("-- ") or line.startswith(">>> ") or line.startswith("Copyright notice"):
                    postambleSeen = True

            if postambleSeen is True:
                self.rDict["Postamble"].append(line)
                line = "POST;" + line
                continue

            body.append(line)

            if "\t" in line:
                line = "TAB;" + line  # mark lines having tabs

            if line.endswith("\r"):
                line = "CR;" + line  # mark lines having CR (\r)

            rr.append(line)

        body = self.cleanSection(body)
        self.rDict["Body"] = self.splitBodyInSections(body)
        return "\n".join(rr), self.rDict

    def printMe(self) -> None:
        zz = ["Preamble", "Percent", "Postamble"]
        for k in zz:
            n = 0
            for lines in self.rDict[k]:
                tab = " [TAB] " if "\t" in lines else ""  # tabs are present in this section
                cr = " [CR] " if "\r" in lines else ""  # \r is present in this section
                print(k, cr, tab, lines)

        k = "Body"
        if len(self.rDict[k]):
            n = 0
            for lines in self.rDict[k]:
                ws = " [WHITESPACE AT END] " if re.search(r"[ \t]+\r?\n", lines) else ""
                tab = " [TAB] " if "\t" in lines else ""  # tabs are present in this section
                cr = " [CR] " if "\r" in lines else ""  # \r is present in this section
                print(f"# --- {k} Section: {n} {cr}{tab}{ws}")
                n += 1
                print(lines)


def prepItem(d: str) -> None:
    if PrintJson is False:
        print("")
        print(f"test domain: <<<<<<<<<< {d} >>>>>>>>>>>>>>>>>>>>")


def xType(x: Any) -> str:
    s = f"{type(x)}"
    return s.split("'")[1]


def testItem(
    d: str,
    printgetRawWhoisResult: bool = False,
) -> None:
    global PrintGetRawWhoisResult
    global SIMPLISTIC
    global WithRedacted

    timeout = 30  # seconds

    w = whois.query(
        d,
        ignore_returncode=IgnoreReturncode,
        verbose=Verbose,
        internationalized=True,
        include_raw_whois_text=PrintGetRawWhoisResult,
        timeout=timeout,
        simplistic=SIMPLISTIC,
        withRedacted=WithRedacted,
    )

    if w is None:
        print("None")
        print("\n", whois.get_last_raw_whois_data())
        return

    # the 3 date time items can be None if not present or a datetime string
    # dnssec is a bool
    # some strings are return as '' when empty (status)
    # statuses can be a array of one empty string if no data

    # not all values are always present it mainly depends on whet we see in the output of whois
    # if we return not None: the elements that ars always there ars domain_name , tld, dnssec

    wd = w.__dict__
    if PrintJson is True:
        for f in ["creation_date", "expiration_date", "last_updated"]:
            if f in wd:
                wd[f] = f"{wd[f]}"
        print(json.dumps(wd))
        return

    for k, v in wd.items():
        if SIMPLISTIC:
            ss = "%-18s "
            if isinstance(v, str):
                print((ss + "'%s'") % (k, v))
            else:
                print((ss + "%s") % (k, v))
        else:
            ss = "%-18s %-17s "
            if isinstance(v, str):
                print((ss + "'%s'") % (k, xType(v), v))
            else:
                print((ss + "%s") % (k, xType(v), v))

    # print("\n", whois.get_last_raw_whois_data())


def errorItem(d: str, e: Any, what: str = "Generic") -> None:
    if what not in Failures:
        Failures[what] = {}
    Failures[what][d] = e

    message = f"Domain: {d}; Exception: {what}; Error: {e}"
    print(message)


def testDomains(aList: List[str]) -> None:
    for d in aList:

        # skip empty lines
        if not d:
            continue

        if len(d.strip()) == 0:
            continue

        # skip comments
        if d.strip().startswith("#"):
            continue

        # skip comments behind the domain
        d = d.split("#")[0]
        d = d.strip()

        prepItem(d)
        try:
            testItem(d)
        except whois.UnknownTld as e:
            errorItem(d, e, what="UnknownTld")
        except whois.FailedParsingWhoisOutput as e:
            errorItem(d, e, what="FailedParsingWhoisOutput")
        except whois.UnknownDateFormat as e:
            errorItem(d, e, what="UnknownDateFormat")
        except whois.WhoisCommandFailed as e:
            errorItem(d, e, what="WhoisCommandFailed")
        except whois.WhoisQuotaExceeded as e:
            errorItem(d, e, what="WhoisQuotaExceeded")
        except whois.WhoisPrivateRegistry as e:
            errorItem(d, e, what="WhoisPrivateRegistry")
        except whois.WhoisCommandTimeout as e:
            errorItem(d, e, what="WhoisCommandTimeout")
        # except Exception as e:
        #    errorItem(d, e, what="Generic")


def getTestFileOne(fPath: str, fileData: Dict[str, Any]) -> None:
    if not os.path.isfile(fPath):  # only files
        return

    if not fPath.endswith(".txt"):  # ending in .txt
        return

    bName = fPath[:-4]
    fileData[bName] = []
    xx = fileData[bName]

    with open(fPath) as f:
        for index, line in enumerate(f):
            line = line.strip()
            if len(line) == 0 or line.startswith("#"):
                continue

            aa = re.split(r"\s+", line)
            if aa[0] not in xx:
                xx.append(aa[0])

    return


def getTestFilesAll(
    tDir: str,
    fileData: Dict[str, Any],
) -> None:
    for item in os.listdir(tDir):
        fPath = f"{tDir}/{item}"
        getTestFileOne(fPath, fileData)


def getAllCurrentTld() -> List[str]:
    return whois.validTlds()


def makeMetaAllCurrentTld(
    allHaving: Optional[str] = None,
    allRegex: Optional[str] = None,
) -> List[str]:
    rr: List[str] = []
    for tld in getAllCurrentTld():
        if allRegex:
            if re.search(allRegex, tld):
                rr.append(f"meta.{tld}")
        else:
            rr.append(f"meta.{tld}")

    return rr


def showAllCurrentTld() -> None:
    print("Tld's currently supported")
    for tld in getAllCurrentTld():
        print(tld)


def ShowRuleset(tld: str) -> None:
    rr = whois.TLD_RE
    if tld in rr:
        for key in sorted(rr[tld].keys()):
            rule = f"{rr[tld][key]}"
            if "re.compile" in rule:
                rule = rule.split("re.compile(")[1]
                rule = rule.split(", re.IGNORECASE)")[0]
            print(key, rule, "IGNORECASE")


def usage() -> None:
    name = os.path.basename(sys.argv[0])

    print(
        f"""
{name}
    [ -h | --usage ]
        print this text and exit

    [ -V | --Version ]
        print the build version string
        and exit

    [ -S | --SupportedTld ]
        print all known top level domains
        and exit

    [ -a | --all]
        test all existing tld currently supported
        and exit

    [ -f <filename> | --file = <filename> " ]
        use the named file to test all domains (one domain per line)
        lines starting with # or empty lines are skipped, anything after the domain is ignored
        the option can be repeated to specify more then one file
        exits after processing all the files

    [ -D <directory> | --Directory = <directory> " ]
        use the named directory, ald use all files ending in .txt as files containing domains
        files are processed as in the -f option so comments and empty lines are skipped
        the option can be repeated to specify more then one directory
        exits after processing all the dirs

    [ -d <domain> | --domain = <domain> " ]
        only analyze the given domains
        the option can be repeated to specify more domain's

    [ -v | --verbose ]
        set verbose to True,
        verbose output will be printed on stderr only

    [ -j | --json ]
        print each result as json

    [ -I | --IgnoreReturncode ]
        sets the IgnoreReturncode to True,

    [ -p | --print ]
        also print text containing the raw output of the cli whois

    [ -R | --Ruleset ]
        dump the ruleset for the requested tld and exit
        should be combined with -d to specify tld's

    [ -C <file> | --Cleanup <file> ]
        read the input file specified and run the same cleanup as in whois.query,
        then exit

    # test two domains with verbose and IgnoreReturncode
    example: {name} -v -I -d meta.org -d meta.com

    # test all supported tld's with verbose and IgnoreReturncode
    example: {name} -v -I -a

    # test one specific file with verbose and IgnoreReturncode
    example: {name} -v -I -f tests/ok-domains.txt

    # test one specific directory with verbose and IgnoreReturncode
    example: {name} -v -I -D tests

"""
    )

    """
    TODO
    --all --reg <re>
        from all tld a regex match sub selection

    --all --having <name>
        from all but only the ones haveing a certain field
    """
    sys.exit(1)


def showFailures() -> None:
    if len(Failures):
        print("\n# ========================")
        for i in sorted(Failures.keys()):
            for j in sorted(Failures[i].keys()):
                print(i, j, Failures[i][j])


def main() -> None:
    global PrintJson
    global Verbose
    global IgnoreReturncode
    global PrintGetRawWhoisResult
    global Ruleset
    global SIMPLISTIC
    global WithRedacted

    name: str = os.path.basename(sys.argv[0])
    if name == "test2.py":
        SIMPLISTIC = False
    else:
        SIMPLISTIC = True

    try:
        opts, args = getopt.getopt(
            sys.argv[1:],
            "jRSpvVIhaf:d:D:r:H:C:",
            [
                "json",
                "Ruleset",
                "SupportedTld",
                "print",
                "verbose",
                "Version",
                "IgnoreReturncode",
                "all",
                "file=",
                "Directory=",
                "domain=",
                "reg=",
                "having=",
                "Cleanup=",
                "withRedacted",
            ],
        )
    except getopt.GetoptError:
        usage()
        sys.exit(2)

    testAllTld: bool = False

    allHaving: Optional[str] = None  # from all supported tld only process the ones having this :: TODO ::
    allRegex: Optional[str] = None  # from all supported tld process only the ones matching this regex

    directory: Optional[str] = None
    dirs: List[str] = []

    filename: Optional[str] = None
    files: List[str] = []

    domain: Optional[str] = None
    domains: List[str] = []

    fileData: Dict[str, Any] = {}

    for opt, arg in opts:
        if opt in ("-S", "SupportedTld"):
            for tld in sorted(whois.validTlds()):
                print(tld)
            sys.exit(0)

        if opt in ("-V", "Version"):
            print(whois.getVersion())
            sys.exit(0)

        if opt == "-h":
            usage()
            sys.exit(0)

        if opt in ("--withRedacted"):
            WithRedacted = True

        if opt in ("-a", "--all"):
            testAllTld = True

        if opt in ("-H", "--having"):
            testAllTld = True
            allHaving = str(arg)

        if opt in ("-r", "--reg"):
            testAllTld = True
            allRegex = str(arg)

        if opt in ("-v", "--verbose"):
            Verbose = True

        if opt in ("-p", "--print"):
            PrintGetRawWhoisResult = True

        if opt in ("-j", "--json"):
            PrintJson = True

        if opt in ("-R", "--Ruleset"):
            Ruleset = True

        if opt in ("-D", "--Directory"):
            directory = arg
            isDir = os.path.isdir(directory)
            if isDir is False:
                print(f"{directory} cannot be found or is not a directory", file=sys.stderr)
                sys.exit(101)

        if opt in ("-C", "--Cleanup"):
            inFile = arg
            isFile = os.path.isfile(arg)
            if isFile is False:
                print(f"{inFile} cannot be found or is not a file", file=sys.stderr)
                sys.exit(101)

            rc = ResponseCleaner(inFile)
            d1, rDict = rc.cleanupWhoisResponse()
            rc.printMe()
            sys.exit(0)

        if opt in ("-f", "--file"):
            filename = arg
            isFile = os.path.isfile(filename)
            if isFile is False:
                print(f"{filename} cannot be found or is not a file", file=sys.stderr)
                sys.exit(101)

            if filename not in files:
                files.append(filename)
                testAllTld = False

        if opt in ("-d", "--domain"):
            domain = arg
            if domain not in domains:
                domains.append(domain)

    if Verbose:
        print(f"{name} SIMPLISTIC: {SIMPLISTIC}", file=sys.stderr)

    if Ruleset is True and len(domains):
        for domain in domains:
            ShowRuleset(domain)
        sys.exit(0)

    if testAllTld:
        allMetaTld = makeMetaAllCurrentTld(allHaving, allRegex)
        testDomains(allMetaTld)
        showFailures()
        sys.exit(0)

    if len(dirs):
        fileData = {}
        for dName in dirs:
            getTestFilesAll(dName, fileData)
        for testFile in fileData:
            testDomains(fileData[testFile])
        showFailures()
        sys.exit(0)

    if len(files):
        fileData = {}
        for testFile in files:
            getTestFileOne(testFile, fileData)
        for testFile in fileData:
            testDomains(fileData[testFile])
        showFailures()
        sys.exit(0)

    if len(domains):
        testDomains(domains)
        showFailures()
        sys.exit(0)

    usage()
    sys.exit(0)


if __name__ == "__main__":
    main()
