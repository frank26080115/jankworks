nmap -p 80 192.168.1.0/24 -oG - | findstr /R /C:"80/open"
pause