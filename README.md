### EBS Consistent Snapshot Creator

A Python script for creating consistent snapshots of EBS volumes on Amazon EC2. Inspired by [ec2-consistent-snapshot](https://github.com/alestic/ec2-consistent-snapshot) written in Perl by Eric Hammond.

The Perl version is a bit of a hassle to install on some systems other than Ubuntu (e.g. CentOS), and I wanted something with as little system dependencies as possible

##### Features:

* Automatically detects the file system format and freezes the file system for a consistent snapshot (file system is unfrozen after snapshot is done). A sync command is also called before the file system freeze to flush any recent changes to disk
* If taking snapshots of MySQL data, tables are locked before file system is frozen, and unlocked after file system is unfrozen to ensure consistent database state
* If taking snapshots of a MySQL replication slave, (optionally) replication can be stopped and restarted during table locks to minimize memory usage

##### Requirements:

* Only certain Linux systems supported, including CentOS 5.x and CentOS 6.x. Does not support OS X
* Python 2.6.x or later
* MySQL-Python (if using on a volume with MySQL data)
* boto (for interfacing with EC2)
* Works best on volumes with XFS file system (for completely consistent snapshots)

##### How to Use:

1. Add the AWS accont credentials near the top of ebs-consistent-snapshot.py
2. Modify the parameters on the top of the main function in ebs-consistent-snapshot.py to match the desired settings
3. Run `python ebs-consistent-snapshot.py` with a single argument, the local device name of the drive to snapshot (e.g. /dev/xvde)