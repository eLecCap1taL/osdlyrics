./autogen.sh
./configure --prefix=/usr PYTHON=/usr/bin/python3
make clean
sudo make uninstall
make
sudo make install