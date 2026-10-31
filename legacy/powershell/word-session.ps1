
param (
    [switch]$Pause,
    [string]$Action,
    [string]$SessionFileName
)
 
$global:sessionPath = $env:USERPROFILE + "\.word-sessions"
$global:inputFile = $SessionFileName

function writeWordSessionFile {
    param (
        $openDocumentsList
    )

  
    New-Item -ItemType Directory -Force -Path $sessionPath | Out-Null
    $outputFile = $sessionPath + "\" + (Get-Date -Format "yyyyMMddTHHmmss") + "-Word-session.json"

    Write-Host "### Saving session to $outputFile"
    ConvertTo-Json  @{ sessions = $openDocumentsList } | Write-Host
    ConvertTo-Json @{ sessions = $openDocumentsList }  | Out-File $outputFile
}

function getFileGUI {
	# Load the necessary assembly
Add-Type -AssemblyName System.Windows.Forms

# Create an OpenFileDialog object
$OpenFileDialog = New-Object System.Windows.Forms.OpenFileDialog

# Set properties for the dialog
$OpenFileDialog.InitialDirectory = $sessionPath
$OpenFileDialog.Filter = "Session files (*.json)|*.*"
$OpenFileDialog.Title = "Select a session file"

# Show the dialog and get the result
$DialogResult = $OpenFileDialog.ShowDialog()

# Check if the user selected a file
if ($DialogResult -eq [System.Windows.Forms.DialogResult]::OK) {
    # Get the selected file path
    $global:inputFile = $OpenFileDialog.FileName
    Write-Host "Selected session file: $inputFile"
} else {
    Write-Host "No file selected."
	Return
}
	
}

function getOpenDocumentsList {
    $openDocumentsList = @()
    . {
        # Load the Word application

        try {
            $word = [Runtime.Interopservices.Marshal]::GetActiveObject('Word.Application')
        }
        catch {
            Write-Host "Unable to get running Word instance."
            throw
            Return
        }


        # Get all open documents
        $documentsLive = $word.Documents

        # Display the names of all open documents
        foreach ($docLive in $documentsLive) {
    
            $docLive.Activate() # Activate the document
            $selection = $word.Selection
            
            $openDocumentInfo = [ordered]@{ }
            $openDocumentInfo.FullName = $docLive.FullName
            $openDocumentInfo.cursorLine = $selection.Information([Microsoft.Office.Interop.Word.WdInformation]::wdFirstCharacterLineNumber)
            $openDocumentInfo.pageNumber = $selection.Range.Information([Microsoft.Office.Interop.Word.WdInformation]::wdActiveEndPageNumber)
    
            $openDocumentsList += $openDocumentInfo 
    
            Write-Host (ConvertTo-Json $openDocumentInfo)
        }
        # Clean up
        [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word)
    } | Out-Null
    
    $openDocumentsList
    return 
}


if (-not $Action) { 
    $Action = "GetDocuments" 
    # $Action = "WriteSession" 
    # $Action = "LoadSession" 
	$Pause=$true
}

if ("LoadSession" -in $Action){
	if (-not $SessionFileName){ getfileGUI	}
}

$Error.Clear()


if ( ("WriteSession" -in $Action) ) {
    $openDocumentsList = @(getOpenDocumentsList)
    ConvertTo-Json $openDocumentsList | Write-Output

}

if ("WriteSession" -in $Action) {
    $openDocumentsList = @(getOpenDocumentsList)
    writeWordSessionFile($openDocumentsList)
}


if ( "LoadSession" -in $Action ) {
    Write-Host "Loading session $inputFile"
try{
    $openDocumentsList = (Get-Content -Path $global:inputFile | Out-String | ConvertFrom-Json).sessions
}
catch{
	throw
	Exit
}
    # Create a new instance of Word application
    $word = New-Object -ComObject Word.Application
    $word.Visible = $true

    foreach ( $doc in $openDocumentsList) {
        # Go to the specified line number
        Write-Host "Opening $($doc.FullName)"
        Write-Host "        at line $($doc.cursorLine)"
        # Open th   e document
        $word.Documents.Open($doc.FullName) | Out-Null
        ( $selection = $word.Selection ) | Out-Null
        $selection.GoTo(3, 1, $doc.cursorLine) | Out-Null
    }
}


if ($Error.Count -gt 0){
    Write-Host "Errors Occured"
    $Pause=$true
}

if ($Pause) {
    Read-Host -Prompt "Press any key to continue..."
}
