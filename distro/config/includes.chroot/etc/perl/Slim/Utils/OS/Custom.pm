package Slim::Utils::OS::Custom;

# Osmium Sound: Lyrion's hook for appliance vendors. Slim::Utils::OSDetect
# loads Slim::Utils::OS::Custom when it is found in @INC. Lyrion itself lives
# under /data/lyrion/current (/usr/share/perl5/Slim is a symlink into it), so
# this file sits in /etc/perl, the first @INC entry of Debian's perl, and
# survives Lyrion updates.
#
# Everything is inherited from the stock Debian support; only the OS name
# changes, so Settings > Information and Lyrion's anonymous analytics report
# "Osmium Sound" instead of "Debian".

use strict;
use base qw(Slim::Utils::OS::Debian);

sub initDetails {
	my $class = shift;

	$class->{osDetails} = $class->SUPER::initDetails();
	$class->{osDetails}->{osName} = 'Osmium Sound';

	return $class->{osDetails};
}

1;
