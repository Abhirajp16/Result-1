Set-Location "D:\abhi\vtu result fetch\Recaptcha"
$process = Start-Process -NoNewWindow -FilePath "C:\Users\Rajesh\AppData\Local\Programs\Python\Python310\python.exe" -ArgumentList "app.py" -PassThru
$process.Id | Out-File "D:\abhi\vtu result fetch\Recaptcha\server_pid.txt"
$process.WaitForExit()
