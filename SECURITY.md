# Security policy

## Reporting a vulnerability

**Please do not report it in public.** Use GitHub's private vulnerability
reporting on this repository: the **Security** tab, then *Report a
vulnerability*. It reaches only the maintainer and does not require
exchanging email addresses. If it is unavailable to you, get in touch through
**[radioterapia.ai](https://radioterapia.ai)** and say only that you have a
security report; the details can then move to a private channel.

**Never attach patient data**, here or anywhere else: no DICOM series, no STL
made from a patient (its inner face is the patient's skin surface), no
screenshot of a patient image, no log with a patient ID, a UID or a series
path. Describe the problem in words, or reproduce it with the synthetic
phantoms the batteries build.

## What is in scope

The code in this repository: the bolus, the mould and the surface applicator.
The installer, the updater and the shell shared by the six apps live in the
[Local Suite](https://github.com/drhenriquebraga/local-suite) repository; a
finding there can be reported here or there. The findings that matter most:

- Anything that writes a name or a UID into an STL file, or exports one
  without the warning the screen shows first.
- Anything that sends image data off the workstation, or puts a patient's
  folder path in a URL.

The libraries this app uses are their authors' work: a problem in one of them
belongs with its authors.

## Not a medical device

Teaching and research material, not a medical device, not validated for
clinical use: a clinically wrong result is a correctness bug, not a
vulnerability, and is welcome through
**[radioterapia.ai](https://radioterapia.ai)**, without patient data.

## Supported versions

The latest Local Suite release, and the tag of this app that it pins.
Single maintainer, no backports.
