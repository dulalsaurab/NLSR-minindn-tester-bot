""" Test NLSR with Mini-NDN and post comments on Gerrit """

import time
import subprocess
import os
import sys
import argparse
import json
import shutil

from pygerrit2.rest import GerritRestAPI
from pygerrit2.rest import GerritReview
from pygerrit2.rest.auth import HTTPDigestAuthFromNetrc

class TestNLSR(object):
    """ Test NLSR class """

    # pylint: disable=too-many-instance-attributes
    def __init__(self, options):
        self.exp_file = os.path.abspath(options.exp_file)
        self.work_dir = os.path.abspath(options.work_dir)
        self.exp_names = ""
        self.record_file = "{}/record.json".format(self.work_dir)
        self.ndncxx_dir = "{}/ndn-cxx".format(self.work_dir)
        self.nfd_dir = "{}/NFD".format(self.work_dir)
        self.nlsr_dir = "{}/NLSR".format(self.work_dir)
        self.url = "https://gerrit.named-data.net"
        self.auth = HTTPDigestAuthFromNetrc(url=self.url)
        self.rest = GerritRestAPI(url=self.url, auth=self.auth)
        self.rev = GerritReview()
        self.tested = {}
        if not os.path.exists(self.record_file) or \
           os.stat(self.record_file).st_size == 0:
            self.tested = {}
        else:
            with open(self.record_file) as f:
                self.tested = json.load(f)
        self.message = ""
        self.score = 0
        self.labels = {}
        # Need to check whether these directories exist first
        #subprocess.call("rm -rf {}/build".format(self.ndncxx_dir).split())
        #subprocess.call("rm -rf {}/build".format(self.nfd_dir).split())
        #subprocess.call("rm -rf {}/build".format(self.nlsr_dir).split())
        #REMOVE # FROM ABOVE LINES
        self.clearTmp()

    def clearTmp(self):
        os.chdir("/tmp")
        dir = [d for d in os.listdir('/tmp') if os.path.isdir(os.path.join('/tmp', d))]
        for f in dir:
            if not f.startswith('.'):
                shutil.rmtree(f)

    def update_src(self, source):
        """ Update dependency helper """
        os.chdir(source)
        update_needed = subprocess.check_output("git pull".split())
        # Is upto date and build folder exists
        if update_needed.strip() == "Already up-to-date." and \
           os.path.isdir("{}/build".format(source)):
            print "{} already up to date".format(source)
            #if not os.path.isdir(full_source.format("build")):
            return 0
        subprocess.call("./waf distclean".split())
        if self.nlsr_dir != source:
            if self.nfd_dir == source:
                ret = subprocess.call("./waf configure --without-websocket".split())
            else:
                ret = subprocess.call("./waf configure".split())
            ret = subprocess.call("./waf")
            print ret
            if ret != 0:
                return ret
            return subprocess.call("sudo ./waf install".split())
        return 0

    def update_dep(self):
        """ Update dependencies """
        directory = [self.ndncxx_dir, self.nfd_dir, self.nlsr_dir]
        for source in directory:
            print source
            dir_name = source.split("/")[len(source.split("/"))-1]
            # dir does not exist or build folder does not exists (i.e. no compilation has been done yet)
            if not os.path.isdir(source): #or not os.path.isdir(full_source.format("build")):
                clone = "git clone --depth 1 https://github.com/named-data/{} {}" \
                        .format(dir_name, source)
                subprocess.call(clone.split())
            ret = self.update_src(source)
            if ret != 0:
                return ret
        return 0

    def clean_up(self, change_id):
        """ Clean up git NLSR"""
        print "Cleaning NLSR git branch"
        subprocess.call("git checkout master".split())
        print subprocess.check_output("git branch -v".split())
        subprocess.call("git branch -D {}".format(change_id).split())

    def has_code_changes(self):
        """ Check if the patch has code changes """
        os.chdir(self.nlsr_dir)
        out = subprocess.check_output("git diff --name-status HEAD~1".split())
        if "cpp" in out or "hpp" in out or "wscript" in out:
            return True
        return False

    def test_minindn(self):
        """ Convergence test """
        self.exp_names = ""
        with open(self.exp_file) as test_file:
            for line in test_file:
                exp = line.split(":")
                test_name = exp[0]
                print "Running minindn test {}".format(test_name)
                print test_name
                self.exp_names += test_name + "\n\n"
                proc = subprocess.Popen(exp[1].split())
                proc.wait()
                self.clearTmp()
                os.chdir(self.nlsr_dir)
                if proc.returncode == 1:
                    return 1, test_name
        return 0, test_name

    def test(self):
        """ Update and run test """
        os.chdir(self.nlsr_dir)
        self.message = ""
        subprocess.call("./waf distclean".split())
        subprocess.call("./waf configure".split())
        subprocess.call("./waf")
        subprocess.call("sudo ./waf install".split())
        code, test = self.test_minindn()
        if code == 1:
            print "Test {} failed!".format(test)
            self.message = "Test {} failed!".format(test)
            self.score = -1
            return 1
        else:
            print "All tests passed!"
            self.message = "All tests passed! \n\n"
            self.message += self.exp_names
            print self.message
            self.score = 1
        return 0

    def get_changes_to_test(self):
        """ Pull the changes testable patches """
        # Get open NLSR changes already verified by Jenkins and mergable
        changes = self.rest.get("changes/?q=status:open+project:NLSR+ \
                                reviewedby:jenkins+is:mergeable+label:verified")

        # iterate over testable changes
        for change in changes:
            print "Checking patch: {}".format(change['subject'])
            change_id = change['change_id']
            print change_id
            change_num = change['_number']

            current_rev = self.rest.get("/changes/?q={}&o=CURRENT_REVISION".format(change_num))
            #print current_rev
            tmp = current_rev[0]['revisions']
            for item in tmp:
                patch = tmp[item]['_number']
                ref = tmp[item]['ref']
            print patch
            print ref

            #comments = self.rest.get("/changes/{}/revisions/{}/review/".format(change_id, patch))
            #print comments['labels']['Verified']['all']
            #for cmnt in comments['labels']['Verified']['all']:
            #    print cmnt

            if change_id in self.tested:
                print "Already tested!"
                #USE A FILE INSTEAD OF SELF.TESTED SO THAT WE CAN RECOVER FROM FATAL FAILURES
                # check if the change has been merged/abandoned, if so remove from tested
                if self.rest.get("changes/?q=status:open+%s" % change_num) is None:
                    self.tested.pop(change_id, None)
                    # clear the file
                    open(self.record_file, 'w').close()
                    # update contents of the file
                    with open(self.record_file, 'w') as f:
                        json.dump(self.tested, f)
                        f.close()
                    continue
            else:
                # update source
                if self.update_dep() != 0:
                    print "Unable to compile!"
                    self.rev.set_message("Unable to compile this patch!")
                    self.rev.add_labels({'Verified': 0})
                else:
                    print "Pulling patch to a new branch..."
                    subprocess.call("git checkout -b {}".format(change_id).split())
                    patch_download_cmd = "git pull {}/NLSR {}".format(self.url, ref)
                    print patch_download_cmd
                    subprocess.call(patch_download_cmd.split())

                    # Check if there has been a change in cpp, hpp, or wscript files
                    if self.has_code_changes():
                        # Test the change
                        print "Testing NLSR patch"
                        self.test()
                        print "Commenting"
                        self.rev.set_message(self.message)
                        self.rev.add_labels({'Verified': self.score})
                    else:
                        print "No change in code"
                        self.rev.set_message("No change in code, skipped testing!")
                        self.rev.add_labels({'Verified': 0})
                print self.rev
                self.rest.review(change_id, patch, self.rev)
                # clean the NLSR directory
                self.clean_up(change_id)
                self.tested[change_id] = ref
                # clear the file
                open(self.record_file, 'w').close()
                # write contents to the file
                with open(self.record_file, 'w') as f:
                    json.dump(self.tested, f)
                    f.close()
            print "\n--------------------------------------------------------\n"
            time.sleep(30)

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Mini-NDN NLSR tester for gerrit')

    parser.add_argument('exp_file', help='specify experiment file')

    parser.add_argument('work_dir', help='specify working dir other than /tmp')

    args = parser.parse_args()
    print args.exp_file
    print args.work_dir

    TEST = TestNLSR(args)

    while 1:
        TEST.get_changes_to_test()
        time.sleep(900)
