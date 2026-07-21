import jenkins.model.Jenkins

def hook = new File('/var/jenkins_home/init.groovy.d/run-linkrag-test-once.groovy')
def job = Jenkins.get().getItemByFullName('linkrag-test')

if (job != null && !job.isBuilding()) {
    job.scheduleBuild2(5)
}

hook.delete()
