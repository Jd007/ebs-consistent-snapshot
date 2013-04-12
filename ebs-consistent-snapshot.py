#!/usr/bin/env python

import os, sys, subprocess
import time, datetime
import MySQLdb
import boto.ec2

EXEC_REQUIREMENTS = ['df', 'fsfreeze'] # List of required executables on the system

AWS_ACCESS_KEY = '' # Fill in the AWS access key here
AWS_SECRET_KEY = '' # AWS secret key

def execute_shell_command(command_str):

	'''
	Given a shell command string, executes it, waits for it to exit, then returns the return code,
	standard output, and standard error as a 3-tuple. The two outputs are returned as lists of str
	outputs, one line at a time in the order that they were printed.

	Command string input is executed in the default shell without question, the caller should ensure
	that the command is trusted for security reasons (not recommended to run arbitrary user input).
	'''

	proc = subprocess.Popen(command_str, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	return_code = proc.wait()
	std_out = []
	std_err = []
	for line in proc.stdout:
		std_out.append(line.rstrip())
	for line in proc.stderr:
		std_err.append(line.rstrip())
	return (return_code, std_out, std_err)

def find_exec(exec_name):

	'''
	Given the name of an executable, attempts to find its location using the PATH environment variable.
	If it cannot be found there, the "which" command is then used to try to find the executable, if
	possible.

	Returns the path fo the executable if it is found, None otherwise.
	'''

	which_exists = False
	for path in os.environ.get('PATH', '').split(':'):
		if os.path.exists(os.path.join(path, exec_name)) and not os.path.isdir(os.path.join(path, exec_name)):
			return os.path.join(path, exec_name)
		if os.path.exists(os.path.join(path, 'which')) and not os.path.isdir(os.path.join(path, 'which')):
			which_exists = True

	if which_exists:
		return_code, stdout, stderr = execute_shell_command('which ' + exec_name.strip())
		if return_code != 0:
			return None
		else:
			return stdout[0]

	return None

def check_requirements(exec_list):
	# Check if all executables in the list
	for exec_name in exec_list:
		if find_exec(exec_name) is None:
			return (-1, exec_name)
	return (0, '')

def get_file_system_format(fs_device_name):

	'''
	Attempts to find the file system format and mount point for the device named fs_device_name.

	Returns a 2-tuple containing the detected file system format name and the mount point as strs,
	if detected. Otherwise the return is (None, <mounted_device_list_as_str>)
	'''

	return_code, stdout, stderr = execute_shell_command('df -T')
	if return_code != 0:
		return (None, '. '.join(stderr))
	else:
		header = stdout[0].lower()
		header = header.replace('mounted on', 'mounted_on')
		fields = header.split()
		fs_name_index = -1
		fs_type_index = -1
		mount_point_index = -1
		for i, field in enumerate(fields):
			if field == 'filesystem':
				fs_name_index = i
			elif field == 'type':
				fs_type_index = i
			elif field == 'mounted_on':
				mount_point_index = i
		if fs_name_index < 0 or fs_type_index < 0 or mount_point_index < 0:
			return (None, 'Cannot parse df output, ' + stdout[0])
		for mount_output in stdout[1:]:
			data = mount_output.split()
			if data[fs_name_index].lower().strip() == fs_device_name.lower().strip():
				return (data[fs_type_index].strip(), data[mount_point_index].strip())
		return (None, 'List of devices detected:\n' + '\n'.join(stdout))

if __name__ == '__main__':

	# Process input args:
	fs_device_to_snapshot = sys.argv[1] # The device to snapshot (e.g. /dev/xvde)

	# Customizable parameters:
	ec2_region = 'us-east-1' # The region to create the snapshot in (example here)
	volume_id = 'vol-somedata' # The ID of the volume to snapshot (example here)
	snapshot_description = '' # Text description of the snapshot (time stamp will be attached after automatically)
	skip_snapshot = True # Whether the actual snapshotting should be skipped (for testing)

	with_mysql = False # Whether to execute the MySQL-specific functions (locking tables)
	stop_slave = False # Whether to stop and restart the slave (if the MySQL server on the snapshotted volume is a replication slave)
	mysql_host = 'localhost' # MySQL server host (most likely localhost)
	mysql_username = 'snap_shot_user' # This user should have RELOAD privileges to acquire locks, and SUPER privilege if stop_slave is True (to stop and restart replication)
	mysql_password = ''

	# Check system compatibility:
	if sys.platform.strip().lower() != 'linux2':
		print 'System %s is not supported.' % sys.platform
		exit(1)

	# Check required programs:
	req_status, req_output = check_requirements(EXEC_REQUIREMENTS)
	if req_status != 0:
		print 'Missing required exec:', req_output
		exit(1)
	print 'System requirements check passed.'

	# Check the file system format and mount point, then set the file system freeze/unfreeze executable
	fs_format, mount_point = get_file_system_format(fs_device_to_snapshot)
	if not fs_format:
		print 'Cannot detect file system format for device:', fs_device_to_snapshot
		print mount_point # mount_point in this case contains the error message
		exit(1)
	fs_freeze_cmd = 'fsfreeze'
	if fs_format == 'xfs' and find_exec('xfs_freeze'):
		fs_freeze_cmd = 'xfs_freeze'
		print 'XFS file system detected.'
	else:
		print 'Non-XFS (%s) file system detected.' % fs_format.upper()

	# Connect to EC2
	ec2_conn = boto.ec2.connect_to_region(ec2_region,
										aws_access_key_id=AWS_ACCESS_KEY,
										aws_secret_access_key=AWS_SECRET_KEY)
	if not ec2_conn:
		print 'Failed to connect to EC2. Nothing has been done, exiting...'
		exit(1)
	else:
		print 'Connected to EC2 successfully.'

	if with_mysql:
		# Connect to MySQL
		try:
			mysql_db = MySQLdb.connect(host=mysql_host, user=mysql_username, passwd=mysql_password, db='')
			db_cursor = mysql_db.cursor()
		except:
			print 'Cannot connect to MySQL server. Nothing has been done, exiting...'
			exit(1)

		# Lock MySQL tables
		print 'Locking MySQL tables...'
		if stop_slave:
			db_cursor.execute("STOP SLAVE")
		db_cursor.execute("FLUSH TABLES WITH READ LOCK")
		print 'MySQL tables locked successfully.'

	# Sync/flush the file system, then lock it
	print 'Flushing and locking file system...'
	error_msg = ''
	try:
		return_code, stdout, stderr = execute_shell_command('sync')
		if return_code != 0:
			error_msg = 'System call sync failed: ' + '\n'.join(stderr)
			assert(1 == 2)
		print 'File system flushed.'
		return_code, stdout, stderr = execute_shell_command(fs_freeze_cmd + ' -f ' + mount_point)
		if return_code != 0:
			error_msg = 'File system freeze call ' + fs_freeze_cmd + ' failed: ' + '\n'.join(stderr)
			assert(1 == 2)
		print 'File system locked successfully.'
	except:
		print error_msg
		if with_mysql:
			print 'MySQL tables are not explicitly unlocked but should be unlocked on exit.'
		exit(1)

	# Create the snapshot (if not set to skip)
	if skip_snapshot:
		print 'Snapshot creation skipped.'
	else:
		print 'Creating EBS snapshot...'
		try:
			ec2_conn.create_snapshot(volume_id, snapshot_description + ' ' + str(datetime.datetime.utcnow()).split('.')[0])
		except:
			print 'Snapshot creation failed. Will still attempt to unfreeze file system and unlock MySQL tables...'
		print 'EBS snapshot created successfully.'

	# Unlock the file system
	return_code, stdout, stderr = execute_shell_command(fs_freeze_cmd + ' -u ' + mount_point)
	if return_code != 0:
		# File system unlocked failed, exit here because we do not want to unlock MySQL tables with file system frozen
		print 'File system unfreeze call ' + fs_freeze_cmd + ' failed: ' + '\n'.join(stderr)
		print 'WARNING: file system mounted at %s may still be frozen!!!!!!! MySQL tables are not explicitly unlocked but should be unlocked on exit.' % mount_point
		exit(1)
	print 'File system unlocked successfully.'

	# Unlock MySQL tables
	if with_mysql:
		try:
			db_cursor.execute("UNLOCK TABLES")
			if stop_slave:
				db_cursor.execute("START SLAVE")
			db_cursor.close()
		except:
			print 'MySQL tables failed to unlock (but should be unlocked on exit) or slave failed to start (manual intervention required).'
			exit(1)
		print 'MySQL tables unlocked successfully.'

	print 'Consistent snapshot of EBS volume "%s" created successfully, bye! :P' % volume_id
	exit(0)
