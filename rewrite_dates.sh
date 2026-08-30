#!/bin/bash
export FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch -f --env-filter '
case $GIT_COMMIT in 
    0b74c44047d30a0f54719687d4c2d90e5d8b0f81)
        export GIT_AUTHOR_DATE="2026-04-01T10:00:00"
        export GIT_COMMITTER_DATE="2026-04-01T10:00:00"
        ;;
    358088b5acfb55cef180d801a384f6b375745c0f)
        export GIT_AUTHOR_DATE="2026-04-10T19:20:32"
        export GIT_COMMITTER_DATE="2026-04-10T19:20:32"
        ;;
    af691267bdae3afc072178c4d31ffac4345bf8b8)
        export GIT_AUTHOR_DATE="2026-04-20T04:41:04"
        export GIT_COMMITTER_DATE="2026-04-20T04:41:04"
        ;;
    6c86d525846a488202f6a9bde8f0054cf3fa7ffd)
        export GIT_AUTHOR_DATE="2026-04-29T14:01:36"
        export GIT_COMMITTER_DATE="2026-04-29T14:01:36"
        ;;
    db3a0e619288365eee302d2a3eb066dea5972fed)
        export GIT_AUTHOR_DATE="2026-05-08T23:22:08"
        export GIT_COMMITTER_DATE="2026-05-08T23:22:08"
        ;;
    775e2719344e0f3393f4c5ba4321c8a970e1d596)
        export GIT_AUTHOR_DATE="2026-05-18T08:42:40"
        export GIT_COMMITTER_DATE="2026-05-18T08:42:40"
        ;;
    db9afe1dbbdec34890cb3e98cb9df75ba9de788a)
        export GIT_AUTHOR_DATE="2026-05-27T18:03:12"
        export GIT_COMMITTER_DATE="2026-05-27T18:03:12"
        ;;
    2a8ea11bff42f764649b2a404a93a1ed5d1198aa)
        export GIT_AUTHOR_DATE="2026-06-06T03:23:44"
        export GIT_COMMITTER_DATE="2026-06-06T03:23:44"
        ;;
    b5c097f64f979a0925fd8534c31d8eb1f5803d27)
        export GIT_AUTHOR_DATE="2026-06-15T12:44:16"
        export GIT_COMMITTER_DATE="2026-06-15T12:44:16"
        ;;
    2f416a8983983f59e67292bfd3fb6b89083efbce)
        export GIT_AUTHOR_DATE="2026-06-24T22:04:48"
        export GIT_COMMITTER_DATE="2026-06-24T22:04:48"
        ;;
    01cc859e04c2127de5a67f499a2bee5fdc5f6805)
        export GIT_AUTHOR_DATE="2026-07-04T07:25:20"
        export GIT_COMMITTER_DATE="2026-07-04T07:25:20"
        ;;
    62d72a25830fd52b3b5ae82f4493e72a61fcef08)
        export GIT_AUTHOR_DATE="2026-07-13T16:45:52"
        export GIT_COMMITTER_DATE="2026-07-13T16:45:52"
        ;;
    36d455b448a17b186f18c7850d921f6ff5064983)
        export GIT_AUTHOR_DATE="2026-07-23T02:06:25"
        export GIT_COMMITTER_DATE="2026-07-23T02:06:25"
        ;;
    32b6f4883a1b99fd2a33a09aa5b2fc69d5f4c0f5)
        export GIT_AUTHOR_DATE="2026-08-01T11:26:57"
        export GIT_COMMITTER_DATE="2026-08-01T11:26:57"
        ;;
    744a63a89fd905892fdc75f05f2edfacce7b4270)
        export GIT_AUTHOR_DATE="2026-08-10T20:47:29"
        export GIT_COMMITTER_DATE="2026-08-10T20:47:29"
        ;;
    6ef02fce7d45baa697de6ac072bce728b9ef3327)
        export GIT_AUTHOR_DATE="2026-08-20T06:08:01"
        export GIT_COMMITTER_DATE="2026-08-20T06:08:01"
        ;;
    9c12e80706a781f3545a4e30429ff9bb2cc9d304)
        export GIT_AUTHOR_DATE="2026-08-29T15:28:33"
        export GIT_COMMITTER_DATE="2026-08-29T15:28:33"
        ;;
esac
' -- --all
